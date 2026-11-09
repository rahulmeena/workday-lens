from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models import ActivityRollup, LLMRun, Message, Window, WindowStatus
from ..schemas import (
    LocalQwenCompletionMetric,
    ResourceBacklogSnapshot,
    ResourceMonitorResponse,
    ResourceProcessSnapshot,
    ResourceQwenSnapshot,
    ResourceThermalSnapshot,
    ResourceThroughputSnapshot,
)
from .local_qwen import LOCAL_QWEN_DISPLAY_MODEL, LOCAL_QWEN_PROVIDER, LOCAL_QWEN_RUNTIME_MODEL, local_qwen_service


ACTIVE_STATUSES = {WindowStatus.QUEUED.value, WindowStatus.PROCESSING.value, WindowStatus.PENDING_LLM.value}


@dataclass(slots=True)
class ProcessInfo:
    pid: int
    cpu_percent: float
    memory_mb: float
    command: str


class ResourceMonitorService:
    def __init__(self, db: Session, *, queue_depth: int) -> None:
        self.db = db
        self.queue_depth = queue_depth

    def snapshot(self) -> ResourceMonitorResponse:
        processes = self._processes()
        local_runs = local_qwen_service.recent_completions()
        qwen_status = local_qwen_service.status()
        qwen_process = self._match_qwen_process(processes, qwen_status)
        process_snapshots = [
            self._snapshot_backend(processes),
            self._snapshot_qwen(qwen_process),
            self._snapshot_first(
                role="capture_helper",
                name="Capture helper",
                processes=processes,
                predicate=lambda item: _is_capture_helper_process(item.command),
            ),
            self._snapshot_first(
                role="frontend",
                name="Dashboard frontend",
                processes=processes,
                predicate=lambda item: "next dev" in item.command or "--port 3001" in item.command,
            ),
        ]
        recent_metrics = [LocalQwenCompletionMetric.model_validate(run) for run in local_runs[-36:]]
        backlog = self._backlog_snapshot()
        throughput = self._throughput_snapshot(recent_metrics=recent_metrics, backlog=backlog)
        qwen = self._qwen_snapshot(
            status=qwen_status,
            process=qwen_process,
            recent_metrics=recent_metrics,
            throughput=throughput,
        )
        captured_at = datetime.now(timezone.utc)
        return ResourceMonitorResponse(
            captured_at=captured_at,
            qwen=qwen,
            thermal=self._thermal_snapshot(captured_at=captured_at),
            processes=process_snapshots,
            backlog=backlog,
            throughput=throughput,
            recent_completions=recent_metrics,
            recommendations=self._recommendations(qwen=qwen, backlog=backlog, throughput=throughput),
        )

    def _backlog_snapshot(self) -> ResourceBacklogSnapshot:
        window_counts: dict[str, int] = {}
        window_tokens: dict[str, int] = {}
        rows = self.db.execute(
            select(Window.status, func.count(Window.id), func.coalesce(func.sum(Window.token_count), 0)).group_by(Window.status)
        ).all()
        for status, count, token_count in rows:
            key = _status_key(status)
            window_counts[key] = int(count or 0)
            window_tokens[key] = int(token_count or 0)

        rollup_counts: dict[str, int] = {}
        rollup_rows = self.db.execute(
            select(ActivityRollup.status, func.count(ActivityRollup.id)).group_by(ActivityRollup.status)
        ).all()
        for status, count in rollup_rows:
            rollup_counts[_status_key(status)] = int(count or 0)

        active_windows = sum(window_counts.get(status, 0) for status in ACTIVE_STATUSES)
        active_tokens = sum(window_tokens.get(status, 0) for status in ACTIVE_STATUSES)
        window_seconds = max(float(settings.window_max_seconds), 1.0)
        return ResourceBacklogSnapshot(
            queue_depth=int(self.queue_depth),
            queued_windows=window_counts.get(WindowStatus.QUEUED.value, 0),
            processing_windows=window_counts.get(WindowStatus.PROCESSING.value, 0),
            pending_windows=window_counts.get(WindowStatus.PENDING_LLM.value, 0),
            active_windows=active_windows,
            active_window_tokens=active_tokens,
            active_window_minutes=round(active_windows * window_seconds / 60, 2),
            queued_rollups=rollup_counts.get(WindowStatus.QUEUED.value, 0),
            processing_rollups=rollup_counts.get(WindowStatus.PROCESSING.value, 0),
            pending_rollups=rollup_counts.get(WindowStatus.PENDING_LLM.value, 0),
            active_rollups=sum(rollup_counts.get(status, 0) for status in ACTIVE_STATUSES),
        )

    def _throughput_snapshot(
        self,
        *,
        recent_metrics: list[LocalQwenCompletionMetric],
        backlog: ResourceBacklogSnapshot,
    ) -> ResourceThroughputSnapshot:
        db_runs = self._recent_window_runs()
        latency_values = [metric.latency_ms for metric in recent_metrics if metric.latency_ms > 0]
        total_tokens_values = [metric.total_tokens for metric in recent_metrics if metric.total_tokens > 0]
        if not latency_values:
            latency_values = [run.latency_ms for run in db_runs if run.latency_ms > 0]
        if not total_tokens_values:
            total_tokens_values = [run.total_tokens for run in db_runs if run.total_tokens > 0]

        avg_latency_ms = _avg(latency_values)
        avg_tokens = _avg(total_tokens_values)
        avg_prompt_tps = _avg([metric.prompt_tokens_per_second for metric in recent_metrics if metric.prompt_tokens_per_second > 0])
        avg_completion_tps = _avg(
            [metric.completion_tokens_per_second for metric in recent_metrics if metric.completion_tokens_per_second > 0]
        )
        avg_total_tps = _avg([metric.total_tokens_per_second for metric in recent_metrics if metric.total_tokens_per_second > 0])
        if avg_total_tps <= 0 and avg_latency_ms > 0 and avg_tokens > 0:
            avg_total_tps = avg_tokens / max(avg_latency_ms / 1000, 0.001)

        window_seconds = max(float(settings.window_max_seconds), 1.0)
        capture_windows_per_minute = 60 / window_seconds
        windows_per_minute_capacity = 60000 / avg_latency_ms if avg_latency_ms > 0 else 0.0
        keep_up_ratio = windows_per_minute_capacity / capture_windows_per_minute if capture_windows_per_minute > 0 else 0.0
        backlog_change_per_hour = (capture_windows_per_minute - windows_per_minute_capacity) * 60 if avg_latency_ms > 0 else 0.0
        drain_minutes: float | None = None
        drain_rate = windows_per_minute_capacity - capture_windows_per_minute
        if drain_rate > 0 and backlog.active_windows > 0:
            drain_minutes = backlog.active_windows / drain_rate

        return ResourceThroughputSnapshot(
            recent_window_runs=max(len(recent_metrics), len(db_runs)),
            avg_window_latency_ms=round(avg_latency_ms, 1),
            avg_window_tokens=round(avg_tokens, 1),
            avg_prompt_tokens_per_second=round(avg_prompt_tps, 1),
            avg_completion_tokens_per_second=round(avg_completion_tps, 1),
            avg_total_tokens_per_second=round(avg_total_tps, 1),
            windows_per_minute_capacity=round(windows_per_minute_capacity, 2),
            capture_windows_per_minute=round(capture_windows_per_minute, 2),
            keep_up_ratio=round(keep_up_ratio, 2),
            estimated_backlog_change_per_hour=round(backlog_change_per_hour, 1),
            estimated_backlog_drain_minutes=round(drain_minutes, 1) if drain_minutes is not None else None,
        )

    def _qwen_snapshot(
        self,
        *,
        status: dict[str, object],
        process: ProcessInfo | None,
        recent_metrics: list[LocalQwenCompletionMetric],
        throughput: ResourceThroughputSnapshot,
    ) -> ResourceQwenSnapshot:
        return ResourceQwenSnapshot(
            provider=str(status.get("provider") or LOCAL_QWEN_PROVIDER),
            display_name=str(status.get("display_name") or LOCAL_QWEN_DISPLAY_MODEL),
            runtime_model=str(status.get("runtime_model") or LOCAL_QWEN_RUNTIME_MODEL),
            state=str(status.get("state") or "unknown"),
            running=bool(status.get("running")),
            ready=bool(status.get("ready")),
            server_url=str(status["server_url"]) if status.get("server_url") else None,
            ctx_size=int(status.get("ctx_size") or local_qwen_service.ctx_size),
            max_ctx_size=int(status.get("max_ctx_size") or local_qwen_service.max_ctx_size),
            predict_tokens=int(status.get("predict_tokens") or local_qwen_service.predict_tokens),
            threads=int(status.get("threads") or local_qwen_service.threads),
            threads_batch=int(status.get("threads_batch") or local_qwen_service.threads_batch),
            cache_ram_mb=int(status.get("cache_ram_mb") or local_qwen_service.cache_ram_mb),
            pid=process.pid if process else None,
            cpu_percent=round(process.cpu_percent, 1) if process else 0.0,
            memory_mb=round(process.memory_mb, 1) if process else 0.0,
            recent_prompt_tokens_per_second=throughput.avg_prompt_tokens_per_second,
            recent_completion_tokens_per_second=throughput.avg_completion_tokens_per_second,
            recent_total_tokens_per_second=throughput.avg_total_tokens_per_second,
            recent_latency_ms=throughput.avg_window_latency_ms,
        )

    def _thermal_snapshot(self, *, captured_at: datetime) -> ResourceThermalSnapshot:
        rows = (
            self.db.execute(
                select(Message)
                .where(
                    or_(
                        Message.source.like("macos:heartbeat:%"),
                        Message.source.like("macos:system_state:%"),
                    )
                )
                .order_by(Message.captured_at.desc())
                .limit(50)
            )
            .scalars()
            .all()
        )
        for message in rows:
            parsed = _thermal_values_from_text(message.text)
            if parsed is None:
                continue
            state, rank, source = parsed
            message_time = _aware_datetime(message.captured_at)
            return ResourceThermalSnapshot(
                state=state,
                rank=rank,
                source=source,
                captured_at=message_time,
                stale_seconds=round(max((captured_at - message_time).total_seconds(), 0), 1),
            )
        return ResourceThermalSnapshot()

    def _recommendations(
        self,
        *,
        qwen: ResourceQwenSnapshot,
        backlog: ResourceBacklogSnapshot,
        throughput: ResourceThroughputSnapshot,
    ) -> list[str]:
        notes: list[str] = []
        if not qwen.running:
            notes.append("Local Qwen is not running right now, so heat is likely coming from capture, frontend, or another process.")
        if throughput.recent_window_runs == 0 and qwen.running:
            notes.append("No recent Qwen completion sample yet; keep this page open during inference to see pg/s and tg/s.")
        if throughput.recent_window_runs > 0 and throughput.keep_up_ratio < 1:
            notes.append("Inference is slower than capture. Increase the window size, pause rollups, or let OpenAI catch up before returning to local Qwen.")
        if throughput.recent_window_runs > 0 and throughput.keep_up_ratio >= 1.25:
            notes.append("Qwen is currently faster than incoming 1-minute windows, so backlog should drain if capture volume stays similar.")
        if backlog.active_windows > 10:
            notes.append("There is queued analysis work. Heat will stay higher until the active window backlog drains.")
        if backlog.active_rollups > 0:
            notes.append("Rollups are also queued; disabling higher rollups reduces local model work while testing capture.")
        if qwen.memory_mb > 9000:
            notes.append("Qwen memory is high. Keeping context at 32k after large windows and avoiding long rollups will reduce pressure.")
        if qwen.cpu_percent > 250:
            notes.append("Qwen is using several CPU-equivalent cores. Let it catch up plugged in, or pause capture if the Mac gets hot.")
        if not notes:
            notes.append("Resource usage looks balanced for the recent samples.")
        return notes[:5]

    def _recent_window_runs(self) -> list[LLMRun]:
        return list(
            self.db.execute(
                select(LLMRun)
                .where(LLMRun.model_name == LOCAL_QWEN_DISPLAY_MODEL)
                .order_by(LLMRun.created_at.desc())
                .limit(36)
            )
            .scalars()
            .all()
        )

    def _processes(self) -> list[ProcessInfo]:
        try:
            output = subprocess.check_output(
                ["/bin/ps", "axo", "pid=,%cpu=,rss=,command="],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        processes: list[ProcessInfo] = []
        for line in output.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            try:
                pid = int(parts[0])
                cpu_percent = float(parts[1])
                memory_mb = float(parts[2]) / 1024
            except ValueError:
                continue
            processes.append(ProcessInfo(pid=pid, cpu_percent=cpu_percent, memory_mb=memory_mb, command=parts[3]))
        return processes

    def _snapshot_backend(self, processes: list[ProcessInfo]) -> ResourceProcessSnapshot:
        current_pid = os.getpid()
        process = next((item for item in processes if item.pid == current_pid), None)
        return _process_snapshot(role="backend", name="Backend API", process=process)

    def _snapshot_qwen(self, process: ProcessInfo | None) -> ResourceProcessSnapshot:
        return _process_snapshot(role="local_qwen", name="Local Qwen", process=process)

    def _snapshot_first(
        self,
        *,
        role: str,
        name: str,
        processes: list[ProcessInfo],
        predicate: Callable[[ProcessInfo], bool],
    ) -> ResourceProcessSnapshot:
        matches = [item for item in processes if predicate(item)]
        return _process_snapshot(role=role, name=name, process=_combine_processes(matches))

    def _match_qwen_process(self, processes: list[ProcessInfo], status: dict[str, object]) -> ProcessInfo | None:
        server_url = str(status.get("server_url") or "")
        port = server_url.rsplit(":", 1)[-1] if ":" in server_url else ""
        if port:
            port_matches = [item for item in processes if "llama-server" in item.command and port in item.command]
            if port_matches:
                return _combine_processes(port_matches)
        qwen_matches = [
            item
            for item in processes
            if "llama-server" in item.command
            and ("Qwen3.5-4B-GGUF" in item.command or LOCAL_QWEN_RUNTIME_MODEL in item.command)
        ]
        return _combine_processes(qwen_matches)


def _status_key(value: object) -> str:
    raw = getattr(value, "value", str(value))
    text = str(raw).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _avg(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / len(values)


def _combine_processes(processes: list[ProcessInfo]) -> ProcessInfo | None:
    if not processes:
        return None
    if len(processes) == 1:
        return processes[0]
    primary = max(processes, key=lambda item: item.memory_mb)
    return ProcessInfo(
        pid=primary.pid,
        cpu_percent=sum(item.cpu_percent for item in processes),
        memory_mb=sum(item.memory_mb for item in processes),
        command=f"{len(processes)} processes; largest: {primary.command}",
    )


def _process_snapshot(*, role: str, name: str, process: ProcessInfo | None) -> ResourceProcessSnapshot:
    return ResourceProcessSnapshot(
        role=role,
        name=name,
        pid=process.pid if process else None,
        cpu_percent=round(process.cpu_percent, 1) if process else 0.0,
        memory_mb=round(process.memory_mb, 1) if process else 0.0,
        command=process.command if process else None,
        running=process is not None,
    )


def _is_capture_helper_process(command: str) -> bool:
    return command.endswith("/WorkdayLensCapture") or command.startswith(".build/arm64-apple-macosx/debug/WorkdayLensCapture")


def _thermal_values_from_text(text: str) -> tuple[str, int, str] | None:
    normalized = text.replace('\\"', '"')
    state_match = re.search(r'"thermal_state"\s*:\s*"([^"]+)"', normalized)
    if state_match is None:
        state_match = re.search(r"\bthermal_state[=:]([A-Za-z_]+)", normalized)
    if state_match is None:
        return None

    state = state_match.group(1).strip().lower()
    if not state:
        return None
    rank_match = re.search(r'"thermal_state_rank"\s*:\s*(-?\d+)', normalized)
    rank = int(rank_match.group(1)) if rank_match else _thermal_rank(state)
    source_match = re.search(r'"thermal_source"\s*:\s*"([^"]+)"', normalized)
    source = source_match.group(1).strip() if source_match else "process_info"
    return state, rank, source or "process_info"


def _thermal_rank(state: str) -> int:
    return {
        "nominal": 0,
        "fair": 1,
        "serious": 2,
        "critical": 3,
    }.get(state, -1)


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
