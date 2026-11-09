from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock, Thread
from typing import Any


LOCAL_QWEN_PROVIDER = "local_qwen35_4b"
LOCAL_QWEN_DISPLAY_MODEL = "Qwen3.5-4B-Q4_K_M+generic_v8"
LOCAL_QWEN_RUNTIME_MODEL = "unsloth/Qwen3.5-4B-GGUF:Q4_K_M"
LOCAL_QWEN_PROMPT_STYLE = "qwen35_4b_generic_v8"

_LOCAL_DATA_ROOT = Path.home() / "WorkdayLensData"
_DEFAULT_CACHE_ROOT = _LOCAL_DATA_ROOT / "llama_cache"
_DEFAULT_HF_HOME = _LOCAL_DATA_ROOT / "hf_cache"
_DEFAULT_RESULTS_ROOT = _LOCAL_DATA_ROOT / "local_qwen"
_DEFAULT_LLAMA_RELEASE_ROOT = _LOCAL_DATA_ROOT / "llama_cpp_releases" / "b9263" / "llama-b9263"
_CHARS_PER_TOKEN_ESTIMATE = 3
_CTX_GROWTH_STEP = 8192


@dataclass
class LocalQwenCompletion:
    output_text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    prompt_eval_ms: int = 0
    generation_ms: int = 0
    prompt_tokens_per_second: float = 0.0
    completion_tokens_per_second: float = 0.0
    total_tokens_per_second: float = 0.0
    ctx_size: int = 0
    compacted: bool = False
    model_name: str = LOCAL_QWEN_DISPLAY_MODEL
    raw_response: dict[str, Any] | None = None


@dataclass
class LocalQwenRunMetric:
    started_at: datetime
    finished_at: datetime
    ctx_size: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    prompt_eval_ms: int
    generation_ms: int
    prompt_tokens_per_second: float
    completion_tokens_per_second: float
    total_tokens_per_second: float
    compacted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ctx_size": self.ctx_size,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "prompt_eval_ms": self.prompt_eval_ms,
            "generation_ms": self.generation_ms,
            "prompt_tokens_per_second": self.prompt_tokens_per_second,
            "completion_tokens_per_second": self.completion_tokens_per_second,
            "total_tokens_per_second": self.total_tokens_per_second,
            "compacted": self.compacted,
        }


@dataclass
class _ServerHandle:
    base_url: str
    port: int
    ctx_size: int
    process: subprocess.Popen[str]
    stdout_path: Path
    stderr_path: Path
    command: list[str]


class LocalQwenService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._request_lock = Lock()
        self._server: _ServerHandle | None = None
        self._setup_thread: Thread | None = None
        self._setup_state = "idle"
        self._setup_message = "Local Qwen has not been prepared in this process."
        self._last_error = ""
        self._recent_runs: deque[LocalQwenRunMetric] = deque(maxlen=160)

    @property
    def ctx_size(self) -> int:
        return _int_env("WFHS_LOCAL_QWEN_CTX_SIZE", 32768)

    @property
    def max_ctx_size(self) -> int:
        return max(self.ctx_size, _int_env("WFHS_LOCAL_QWEN_MAX_CTX_SIZE", 131072))

    @property
    def predict_tokens(self) -> int:
        return _int_env("WFHS_LOCAL_QWEN_PREDICT_TOKENS", 1024)

    @property
    def threads(self) -> int:
        return max(1, _int_env("WFHS_LOCAL_QWEN_THREADS", 2))

    @property
    def threads_batch(self) -> int:
        return max(1, _int_env("WFHS_LOCAL_QWEN_THREADS_BATCH", self.threads))

    @property
    def cache_ram_mb(self) -> int:
        return max(0, _int_env("WFHS_LOCAL_QWEN_CACHE_RAM_MB", 0))

    @property
    def timeout_seconds(self) -> int:
        return _int_env("WFHS_LOCAL_QWEN_TIMEOUT_SECONDS", 900)

    @property
    def shrink_large_context_after_request(self) -> bool:
        return _bool_env("WFHS_LOCAL_QWEN_SHRINK_LARGE_CTX_AFTER_REQUEST", True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            server = self._server if self._server and self._server.process.poll() is None else None
            if self._server and not server:
                self._server = None
            llama_server_path = self._llama_server_path()
            model_path = self._cached_model_path()
            if server:
                state = "running"
                message = f"Local Qwen is running on {server.base_url}."
            elif self._setup_state in {"preparing", "starting"}:
                state = self._setup_state
                message = self._setup_message
            elif self._last_error:
                state = "error"
                message = self._last_error
            elif not llama_server_path:
                state = "missing_runtime"
                message = "llama-server was not found. Install llama.cpp or set WFHS_LLAMA_SERVER_PATH."
            elif model_path:
                state = "ready"
                message = "Qwen is cached locally and ready to start."
            else:
                state = "not_downloaded"
                message = "Qwen has not been downloaded into the local llama.cpp cache yet."
            return {
                "provider": LOCAL_QWEN_PROVIDER,
                "display_name": LOCAL_QWEN_DISPLAY_MODEL,
                "runtime_model": LOCAL_QWEN_RUNTIME_MODEL,
                "prompt_style": LOCAL_QWEN_PROMPT_STYLE,
                "state": state,
                "message": message,
                "ready": state in {"ready", "running"},
                "running": state == "running",
                "server_url": server.base_url if server else None,
                "ctx_size": server.ctx_size if server else self.ctx_size,
                "max_ctx_size": self.max_ctx_size,
                "predict_tokens": self.predict_tokens,
                "threads": self.threads,
                "threads_batch": self.threads_batch,
                "cache_ram_mb": self.cache_ram_mb,
                "model_path": str(model_path) if model_path else None,
                "llama_server_path": str(llama_server_path) if llama_server_path else None,
                "cache_root": str(self._cache_root()),
                "hf_home": str(self._hf_home()),
                "last_error": self._last_error or None,
            }

    def prepare_async(self) -> dict[str, Any]:
        with self._lock:
            if self._setup_thread and self._setup_thread.is_alive():
                return self.status()
            self._setup_state = "preparing"
            self._setup_message = "Preparing local Qwen. llama.cpp may download the model on first start."
            self._last_error = ""
            self._setup_thread = Thread(target=self._prepare_worker, name="workday-lens-local-qwen-setup", daemon=True)
            self._setup_thread.start()
            return self.status()

    def stop(self) -> None:
        with self._lock:
            server = self._server
            self._server = None
        self._stop_server(server)

    def complete_activity(self, prompt: str) -> LocalQwenCompletion:
        with self._request_lock:
            prompt_to_send = self._chatml_prompt(
                system="You summarize work-activity benchmark evidence. Return strict JSON only.",
                user=prompt,
            )
            required_ctx = self._ctx_size_for_prompt(prompt_to_send)
            server = self.ensure_started(required_ctx)
            try:
                local_prompt = self._compact_prompt_for_server(prompt_to_send, ctx_size=server.ctx_size)
                payload = {
                    "prompt": local_prompt,
                    "n_predict": self.predict_tokens,
                    "temperature": 0,
                    "top_k": 1,
                    "seed": 1,
                    "cache_prompt": True,
                    "stream": False,
                }
                started = time.perf_counter()
                started_at = datetime.now(timezone.utc)
                try:
                    response_json = self._post_json(f"{server.base_url}/completion", payload, timeout=self.timeout_seconds)
                except Exception as exc:
                    self.stop()
                    required_ctx = max(required_ctx, self._ctx_size_for_error(str(exc)))
                    server = self.ensure_started(required_ctx)
                    local_prompt = self._compact_prompt_for_server(prompt_to_send, ctx_size=server.ctx_size)
                    payload["prompt"] = local_prompt
                    response_json = self._post_json(f"{server.base_url}/completion", payload, timeout=self.timeout_seconds)
                latency_ms = int((time.perf_counter() - started) * 1000)
                finished_at = datetime.now(timezone.utc)
                output_text = str(response_json.get("content") or "")
                prompt_tokens, completion_tokens = self._server_usage_tokens(response_json, local_prompt, output_text)
                prompt_eval_ms, generation_ms, prompt_tps, completion_tps = self._server_timing_metrics(
                    response_json,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                total_tokens = prompt_tokens + completion_tokens
                total_tps = total_tokens / max(latency_ms / 1000, 0.001)
                compacted = local_prompt != prompt_to_send
                completion = LocalQwenCompletion(
                    output_text=output_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    prompt_eval_ms=prompt_eval_ms,
                    generation_ms=generation_ms,
                    prompt_tokens_per_second=prompt_tps,
                    completion_tokens_per_second=completion_tps,
                    total_tokens_per_second=total_tps,
                    ctx_size=server.ctx_size,
                    compacted=compacted,
                    raw_response=response_json,
                )
                self._record_run(
                    LocalQwenRunMetric(
                        started_at=started_at,
                        finished_at=finished_at,
                        ctx_size=server.ctx_size,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        latency_ms=latency_ms,
                        prompt_eval_ms=prompt_eval_ms,
                        generation_ms=generation_ms,
                        prompt_tokens_per_second=prompt_tps,
                        completion_tokens_per_second=completion_tps,
                        total_tokens_per_second=total_tps,
                        compacted=compacted,
                    )
                )
                return completion
            finally:
                if self.shrink_large_context_after_request and server.ctx_size > self.ctx_size:
                    with self._lock:
                        if self._server is server:
                            self._server = None
                    self._stop_server(server)

    def recent_completions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [run.as_dict() for run in self._recent_runs]

    def ensure_started(self, min_ctx_size: int | None = None) -> _ServerHandle:
        required_ctx = max(self.ctx_size, int(min_ctx_size or self.ctx_size))
        with self._lock:
            existing = self._server
            if existing and existing.process.poll() is None and existing.ctx_size >= required_ctx:
                self._setup_state = "ready"
                self._setup_message = f"Local Qwen is running on {existing.base_url}."
                return existing
            if existing:
                self._server = None
        if existing and existing.process.poll() is None:
            self._stop_server(existing)
        return self._start_server(ctx_size=required_ctx)

    def _prepare_worker(self) -> None:
        try:
            self.ensure_started(self.ctx_size)
            with self._lock:
                self._setup_state = "ready"
                self._setup_message = "Local Qwen is ready."
                self._last_error = ""
        except Exception as exc:
            with self._lock:
                self._setup_state = "error"
                self._last_error = str(exc)
                self._setup_message = self._last_error

    def _start_server(self, *, ctx_size: int) -> _ServerHandle:
        llama_server_path = self._llama_server_path()
        if not llama_server_path:
            raise RuntimeError("llama-server was not found. Install llama.cpp or set WFHS_LLAMA_SERVER_PATH.")
        self._prepare_runtime_files()
        effective_ctx = max(self.ctx_size, min(self.max_ctx_size, self._round_ctx_size(ctx_size)))
        port = self._free_port()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        log_dir = self._results_root()
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", LOCAL_QWEN_DISPLAY_MODEL).strip("_")
        stdout_path = log_dir / f"llama-server-{safe_model}-{port}-{stamp}.out.log"
        stderr_path = log_dir / f"llama-server-{safe_model}-{port}-{stamp}.err.log"
        command = [
            str(llama_server_path),
            "-hf",
            LOCAL_QWEN_RUNTIME_MODEL,
            "-ngl",
            "999",
            "-c",
            str(effective_ctx),
            "-n",
            str(self.predict_tokens),
            "--threads",
            str(self.threads),
            "--threads-batch",
            str(self.threads_batch),
            "--temp",
            "0",
            "--top-k",
            "1",
            "--seed",
            "1",
            "--reasoning",
            "off",
            "--reasoning-budget",
            "0",
            "--json-schema-file",
            str(self._schema_path()),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--parallel",
            "1",
            "--cache-reuse",
            "256",
            "--cache-ram",
            str(self.cache_ram_mb),
            "--no-webui",
            "--slots",
            "-fa",
            "on",
        ]
        with self._lock:
            self._setup_state = "starting"
            self._setup_message = "Starting llama.cpp server for local Qwen."
            self._last_error = ""
        stdout_handle = stdout_path.open("w", encoding="utf-8", errors="replace")
        stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(llama_server_path.parent),
                env=self._llama_env(),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
        finally:
            stdout_handle.close()
            stderr_handle.close()
        server = _ServerHandle(
            base_url=f"http://127.0.0.1:{port}",
            port=port,
            ctx_size=effective_ctx,
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=command,
        )
        self._wait_for_server(server)
        with self._lock:
            self._server = server
            self._setup_state = "ready"
            self._setup_message = f"Local Qwen is running on {server.base_url}."
            self._last_error = ""
        return server

    def _wait_for_server(self, server: _ServerHandle) -> None:
        deadline = time.monotonic() + max(self.timeout_seconds, 60)
        last_error = ""
        while time.monotonic() < deadline:
            if server.process.poll() is not None:
                raise RuntimeError("llama-server exited before becoming ready. " + self._server_log_tail(server))
            try:
                with urllib.request.urlopen(f"{server.base_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError) as exc:
                last_error = str(exc)
            time.sleep(0.5)
        raise RuntimeError(f"llama-server did not become ready on port {server.port}: {last_error}. {self._server_log_tail(server)}")

    def _stop_server(self, server: _ServerHandle | None) -> None:
        if server and server.process.poll() is None:
            server.process.terminate()
            try:
                server.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.process.kill()
                server.process.wait(timeout=10)

    def _post_json(self, url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama-server HTTP {exc.code}: {body[:1200]}") from exc
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise RuntimeError("llama-server returned a non-object response.")
        return parsed

    def _prepare_runtime_files(self) -> None:
        self._results_root().mkdir(parents=True, exist_ok=True)
        self._cache_root().mkdir(parents=True, exist_ok=True)
        (self._hf_home() / "hub").mkdir(parents=True, exist_ok=True)
        self._schema_path().write_text(json.dumps(local_qwen_output_schema(), ensure_ascii=True, indent=2), encoding="utf-8")

    def _schema_path(self) -> Path:
        return self._results_root() / "activity-summary-schema.json"

    def _cache_root(self) -> Path:
        return Path(os.getenv("WFHS_LLAMA_CACHE_ROOT") or _DEFAULT_CACHE_ROOT).expanduser()

    def _hf_home(self) -> Path:
        return Path(os.getenv("WFHS_HF_HOME") or _DEFAULT_HF_HOME).expanduser()

    def _results_root(self) -> Path:
        return Path(os.getenv("WFHS_LOCAL_QWEN_RESULTS_ROOT") or _DEFAULT_RESULTS_ROOT).expanduser()

    def _llama_server_path(self) -> Path | None:
        candidates = [
            os.getenv("WFHS_LLAMA_SERVER_PATH"),
            str(_DEFAULT_LLAMA_RELEASE_ROOT / "llama-server"),
            _which("llama-server"),
            _homebrew_llama_server(),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.exists() and os.access(path, os.X_OK):
                return path
        return None

    def _cached_model_path(self) -> Path | None:
        pattern = self._cache_root() / "models--unsloth--Qwen3.5-4B-GGUF" / "snapshots" / "*" / "Qwen3.5-4B-Q4_K_M.gguf"
        matches = sorted(pattern.parent.parent.glob("*/Qwen3.5-4B-Q4_K_M.gguf")) if pattern.parent.parent.exists() else []
        return matches[-1] if matches else None

    def _llama_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LLAMA_CACHE"] = str(self._cache_root())
        env["HF_HOME"] = str(self._hf_home())
        env["HUGGINGFACE_HUB_CACHE"] = str(self._hf_home() / "hub")
        env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        server_path = self._llama_server_path()
        if server_path:
            env["PATH"] = str(server_path.parent) + os.pathsep + env.get("PATH", "")
        return env

    def _server_log_tail(self, server: _ServerHandle) -> str:
        chunks = []
        for path in (server.stderr_path, server.stdout_path):
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace")[-2000:])
            except OSError:
                continue
        return "\n".join(chunk for chunk in chunks if chunk).strip()

    def _ctx_size_for_prompt(self, prompt: str) -> int:
        required = self._estimate_prompt_tokens(prompt) + self.predict_tokens + 256
        if required <= self.ctx_size:
            return self.ctx_size
        return min(self.max_ctx_size, self._round_ctx_size(required))

    def _ctx_size_for_error(self, error_message: str) -> int:
        match = re.search(r'"n_prompt_tokens"\s*:\s*(\d+)', error_message)
        if not match:
            match = re.search(r"request \((\d+) tokens\) exceeds", error_message)
        if not match:
            return self.ctx_size
        return min(self.max_ctx_size, self._round_ctx_size(int(match.group(1)) + self.predict_tokens + 256))

    def _round_ctx_size(self, ctx_size: int) -> int:
        return max(self.ctx_size, ((int(ctx_size) + _CTX_GROWTH_STEP - 1) // _CTX_GROWTH_STEP) * _CTX_GROWTH_STEP)

    def _estimate_prompt_tokens(self, prompt: str) -> int:
        char_estimate = (len(prompt) + _CHARS_PER_TOKEN_ESTIMATE - 1) // _CHARS_PER_TOKEN_ESTIMATE
        return max(1, len(prompt.split()), char_estimate)

    def _prompt_token_budget(self, ctx_size: int) -> int:
        return max(128, int(ctx_size) - self.predict_tokens - 256)

    def _compact_prompt_for_server(self, prompt: str, *, ctx_size: int) -> str:
        token_budget = self._prompt_token_budget(ctx_size)
        if self._estimate_prompt_tokens(prompt) <= token_budget:
            return prompt
        char_limit = max(2000, token_budget * _CHARS_PER_TOKEN_ESTIMATE)
        suffix = prompt[-2500:]
        notice = "\n\n[Local llama.cpp note: middle transcript content was omitted to fit context. Prefer unknowns for missing evidence.]\n\n"
        head_budget = max(2000, char_limit - len(suffix) - len(notice))
        return prompt[:head_budget].rstrip() + notice + suffix.lstrip()

    def _server_usage_tokens(self, response_json: dict[str, Any], prompt: str, output_text: str) -> tuple[int, int]:
        timings = response_json.get("timings") if isinstance(response_json.get("timings"), dict) else {}
        prompt_tokens = int(timings.get("prompt_n") or response_json.get("tokens_evaluated") or 0)
        completion_tokens = int(timings.get("predicted_n") or response_json.get("tokens_predicted") or 0)
        if prompt_tokens <= 0:
            prompt_tokens = max(1, len(prompt.split()))
        if completion_tokens <= 0:
            completion_tokens = max(1, len(output_text.split()))
        return prompt_tokens, completion_tokens

    def _server_timing_metrics(
        self,
        response_json: dict[str, Any],
        *,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> tuple[int, int, float, float]:
        timings = response_json.get("timings") if isinstance(response_json.get("timings"), dict) else {}
        prompt_ms = int(float(timings.get("prompt_ms") or 0))
        generation_ms = int(float(timings.get("predicted_ms") or 0))
        prompt_tps = float(timings.get("prompt_per_second") or 0)
        completion_tps = float(timings.get("predicted_per_second") or 0)
        if prompt_tps <= 0 and prompt_ms > 0:
            prompt_tps = prompt_tokens / max(prompt_ms / 1000, 0.001)
        if completion_tps <= 0 and generation_ms > 0:
            completion_tps = completion_tokens / max(generation_ms / 1000, 0.001)
        return prompt_ms, generation_ms, prompt_tps, completion_tps

    def _record_run(self, run: LocalQwenRunMetric) -> None:
        with self._lock:
            self._recent_runs.append(run)

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _chatml_prompt(self, *, system: str, user: str) -> str:
        return "\n".join(
            [
                "<|im_start|>system",
                system,
                "<|im_end|>",
                "<|im_start|>user",
                user,
                "<|im_end|>",
                "<|im_start|>assistant",
                "",
            ]
        )


def local_qwen_output_schema() -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "headline": {"type": "string", "maxLength": 100},
            "summary": {"type": "string", "maxLength": 180},
            "activity_type": {
                "type": "string",
                "enum": ["deep_work", "planning", "research", "review", "communication", "admin", "break", "other"],
            },
            "primary_app": {"type": "string", "maxLength": 100},
            "primary_project": {"type": "string", "maxLength": 100},
            "productivity": {"type": "string", "enum": ["productive", "neutral", "unproductive", "unknown"]},
            "focus_level": {"type": "string", "enum": ["focused", "steady", "switching", "blocked", "idle", "unknown"]},
            "user_goal": {"type": "string", "maxLength": 100},
            "specific_task": {"type": "string", "maxLength": 180},
            "evidence": {"type": "array", "items": {"type": "string", "maxLength": 140}, "maxItems": 3},
            "uncertainty_notes": {"type": "array", "items": {"type": "string", "maxLength": 140}, "maxItems": 3},
            "unsupported_claim_count": {"type": "integer", "minimum": 0, "maximum": 20},
            "contradicted_claim_count": {"type": "integer", "minimum": 0, "maximum": 20},
            "over_specific_claim_count": {"type": "integer", "minimum": 0, "maximum": 20},
            "uncertainty_count": {"type": "integer", "minimum": 0, "maximum": 20},
            "unknown_fields": {"type": "array", "items": {"type": "string", "maxLength": 140}, "maxItems": 3},
            "evidence_coverage_score": {"type": "number", "minimum": 0, "maximum": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "headline",
            "summary",
            "activity_type",
            "primary_app",
            "primary_project",
            "productivity",
            "focus_level",
            "user_goal",
            "specific_task",
            "evidence",
            "uncertainty_notes",
            "unsupported_claim_count",
            "contradicted_claim_count",
            "over_specific_claim_count",
            "uncertainty_count",
            "unknown_fields",
            "evidence_coverage_score",
            "confidence",
        ],
    }
    return schema


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _which(binary: str) -> str | None:
    for directory in os.getenv("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _homebrew_llama_server() -> str | None:
    for prefix in ("/opt/homebrew/opt/llama.cpp", "/usr/local/opt/llama.cpp"):
        candidate = Path(prefix) / "bin" / "llama-server"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


local_qwen_service = LocalQwenService()
