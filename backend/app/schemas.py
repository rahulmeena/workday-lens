from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import WindowStatus


class CaptureBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float
    height: float


class CaptureAncestor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Optional[str] = Field(None, max_length=128)
    subrole: Optional[str] = Field(None, max_length=128)
    name: Optional[str] = Field(None, max_length=1024)
    description: Optional[str] = Field(None, max_length=1024)

    @field_validator("role", "subrole", "name", "description", mode="before")
    @classmethod
    def clamp_ancestor_text(cls, value: Any, info):
        limits = {
            "role": 128,
            "subrole": 128,
            "name": 1024,
            "description": 1024,
        }
        return _clamp_capture_string(value, limits.get(info.field_name, 1024))


class CaptureScreenshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_path: str = Field(..., max_length=2048)
    reason: str = Field(..., max_length=64)
    captured_at: datetime
    width: Optional[int] = Field(None, ge=1)
    height: Optional[int] = Field(None, ge=1)
    sha256: Optional[str] = Field(None, max_length=128)


class CaptureEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["workday_lens_capture_event.v1"] = Field(..., alias="schema")
    event_id: str = Field(..., min_length=1, max_length=128)
    captured_at: datetime
    source_platform: Literal["macos"]
    tag: Literal[
        "foreground",
        "focus_entered",
        "focus",
        "ui_text",
        "value_change",
        "name_change",
        "description_change",
        "state_change",
        "caret",
        "command_key",
        "keyboard_activity",
        "gesture",
        "system_state",
        "mouse_hover",
        "mouse_action",
        "heartbeat",
    ]
    app_name: Optional[str] = Field(None, max_length=256)
    bundle_id: Optional[str] = Field(None, max_length=512)
    process_id: Optional[int] = Field(None, ge=0)
    window_title: Optional[str] = Field(None, max_length=1024)
    window_id: Optional[str] = Field(None, max_length=256)
    window_bounds: Optional[CaptureBounds] = None
    role: Optional[str] = Field(None, max_length=128)
    subrole: Optional[str] = Field(None, max_length=128)
    name: Optional[str] = Field(None, max_length=2048)
    value: Optional[str] = Field(None, max_length=4096)
    description: Optional[str] = Field(None, max_length=2048)
    selected_text: Optional[str] = Field(None, max_length=4096)
    states: list[str] = Field(default_factory=list, max_length=32)
    keyboard_shortcut: Optional[str] = Field(None, max_length=128)
    element_bounds: Optional[CaptureBounds] = None
    ancestors: list[CaptureAncestor] = Field(default_factory=list, max_length=12)
    x: Optional[int] = None
    y: Optional[int] = None
    button: Optional[str] = Field(None, max_length=32)
    state: Optional[str] = Field(None, max_length=32)
    scroll_axis: Optional[str] = Field(None, max_length=32)
    scroll_direction: Optional[str] = Field(None, max_length=32)
    command_key_name: Optional[str] = Field(None, max_length=128)
    screenshot: Optional[CaptureScreenshotMetadata] = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "event_id",
        "app_name",
        "bundle_id",
        "window_title",
        "window_id",
        "role",
        "subrole",
        "name",
        "value",
        "description",
        "selected_text",
        "keyboard_shortcut",
        "button",
        "state",
        "scroll_axis",
        "scroll_direction",
        "command_key_name",
        mode="before",
    )
    @classmethod
    def clamp_capture_text(cls, value: Any, info):
        limits = {
            "event_id": 128,
            "app_name": 256,
            "bundle_id": 512,
            "window_title": 1024,
            "window_id": 256,
            "role": 128,
            "subrole": 128,
            "name": 2048,
            "value": 4096,
            "description": 2048,
            "selected_text": 4096,
            "keyboard_shortcut": 128,
            "button": 32,
            "state": 32,
            "scroll_axis": 32,
            "scroll_direction": 32,
            "command_key_name": 128,
        }
        return _clamp_capture_string(value, limits.get(info.field_name, 1024))


class CaptureEventBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[CaptureEventIn] = Field(..., min_length=1, max_length=500)


def _clamp_capture_string(value: Any, limit: int) -> Any:
    if value is None or not isinstance(value, str) or len(value) <= limit:
        return value
    suffix = " ... [truncated]"
    return value[: max(0, limit - len(suffix))].rstrip() + suffix


class CaptureIngestResponse(BaseModel):
    accepted_events: int
    stored_messages: int
    queued_windows: int


class CaptureMessageItem(BaseModel):
    id: int
    session_id: str
    source: Optional[str] = None
    text: str
    captured_at: datetime
    window_id: Optional[str] = None


class CaptureMessageListResponse(BaseModel):
    data: list[CaptureMessageItem] = Field(default_factory=list)
    latest_id: Optional[int] = None
    has_more: bool = False


class ActivityWindow(BaseModel):
    window_id: str = Field(..., alias="id")
    captured_from: datetime
    captured_to: datetime
    raw_excerpt: str
    llm_summary: str
    verdict: WindowStatus
    confidence: float

    class Config:
        populate_by_name = True


class ActivitySegment(BaseModel):
    window_id: str
    captured_from: datetime
    captured_to: datetime
    duration_minutes: int
    status: WindowStatus
    headline: str
    summary: str
    goal: str
    project: str
    activity_type: str
    activity_label: str
    focus_state: str
    focus_label: str
    next_step: str
    raw_excerpt: str
    confidence: float
    model_name: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class ActivityRollupItem(BaseModel):
    id: str
    level: str
    captured_from: datetime
    captured_to: datetime
    duration_minutes: int
    status: WindowStatus
    headline: str
    summary: str
    dominant_goal: str
    project: str
    activity_type: str
    activity_label: str
    focus_state: str
    focus_label: str
    secondary_goals: list[str] = Field(default_factory=list)
    important_intervals: list[str] = Field(default_factory=list)
    ignored_noise: Optional[str] = None
    confidence: float
    source_count: int
    model_name: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class ActivityRollupListResponse(BaseModel):
    level: str
    data: list[ActivityRollupItem] = Field(default_factory=list)


class ActivityRollupChildrenResponse(BaseModel):
    parent: ActivityRollupItem
    children: list[ActivityRollupItem | ActivitySegment] = Field(default_factory=list)


class ActivityLLMDebugResponse(BaseModel):
    id: str
    level: str
    captured_from: datetime
    captured_to: datetime
    model_name: Optional[str] = None
    prompt_text: str = ""
    response_text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    reconstructed: bool = True
    notes: list[str] = Field(default_factory=list)


class ActivityGanttBlock(BaseModel):
    id: str
    lane: str
    captured_from: datetime
    captured_to: datetime
    label: str
    summary: str
    project: str
    activity_type: str
    focus_state: str
    source_level: str
    source_ids: list[str] = Field(default_factory=list)
    priority_score: float
    reason: str
    is_marker: bool = False
    is_gap: bool = False
    evidence: str = ""
    visual_group: str = ""
    visual_tone: str = ""


class ActivityGanttResponse(BaseModel):
    mode: str
    captured_from: datetime
    captured_to: datetime
    status: str
    model_name: Optional[str] = None
    generated_at: Optional[datetime] = None
    blocks: list[ActivityGanttBlock] = Field(default_factory=list)


class ActivityReprocessRequest(BaseModel):
    level: str
    from_time: datetime = Field(..., alias="from")
    to_time: datetime = Field(..., alias="to")
    mode: str = Field("all", pattern="^(all|pending)$")


class ActivityReprocessResponse(BaseModel):
    level: str
    mode: str
    queued_windows: int = 0
    queued_rollups: int = 0
    invalidated_rollups: int = 0


class ActivityBreakdownItem(BaseModel):
    label: str
    minutes: int
    segments: int


class ActivityDashboardSummary(BaseModel):
    total_tracked_minutes: int
    focused_minutes: int
    activity_switches: int
    active_projects: int
    captured_windows: int
    pending_windows: int
    longest_focus_block_minutes: int


class ActivityDashboardResponse(BaseModel):
    date: date
    summary: ActivityDashboardSummary
    current_intent: Optional[ActivitySegment] = None
    story_headline: Optional[str] = None
    story_summary: Optional[str] = None
    story_model_name: Optional[str] = None
    breakdown: list[ActivityBreakdownItem] = Field(default_factory=list)
    project_breakdown: list[ActivityBreakdownItem] = Field(default_factory=list)
    segments: list[ActivitySegment] = Field(default_factory=list)


class PaginatedResponse(BaseModel):
    data: List[ActivityWindow]
    next_cursor: Optional[str] = None


class PolicyResponse(BaseModel):
    id: str
    text: str
    examples: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime


class PolicyCreateRequest(BaseModel):
    text: str
    examples: Optional[list[str]] = None


class PolicyUpdateRequest(BaseModel):
    text: Optional[str] = None
    examples: Optional[list[str]] = None
    active: Optional[bool] = None


class ViolationItem(BaseModel):
    window_id: str
    captured_from: datetime
    captured_to: datetime
    title: str
    detail: str
    created_at: datetime


class ViolationListResponse(BaseModel):
    data: List[ViolationItem]
    next_cursor: Optional[str] = None


class WindowDetailResponse(BaseModel):
    window_id: str
    session_id: str
    started_at: datetime
    ended_at: datetime
    status: WindowStatus
    token_count: int
    messages: List[str]
    summary: Optional[str] = None
    verdict: Optional[WindowStatus] = None
    confidence: Optional[float] = None
    model_name: Optional[str] = None
    latency_ms: Optional[int] = None


class HealthResponse(BaseModel):
    status: str
    version: str


class MetricsResponse(BaseModel):
    queue_depth: int
    pending_windows: int
    violations_today: int
    last_worker_run: Optional[datetime] = None


class ResourceProcessSnapshot(BaseModel):
    role: str
    name: str
    pid: Optional[int] = None
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    command: Optional[str] = None
    running: bool = False


class ResourceBacklogSnapshot(BaseModel):
    queue_depth: int
    queued_windows: int
    processing_windows: int
    pending_windows: int
    active_windows: int
    active_window_tokens: int
    active_window_minutes: float
    queued_rollups: int
    processing_rollups: int
    pending_rollups: int
    active_rollups: int


class ResourceThroughputSnapshot(BaseModel):
    recent_window_runs: int
    avg_window_latency_ms: float
    avg_window_tokens: float
    avg_prompt_tokens_per_second: float
    avg_completion_tokens_per_second: float
    avg_total_tokens_per_second: float
    windows_per_minute_capacity: float
    capture_windows_per_minute: float
    keep_up_ratio: float
    estimated_backlog_change_per_hour: float
    estimated_backlog_drain_minutes: Optional[float] = None


class LocalQwenCompletionMetric(BaseModel):
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
    compacted: bool = False


class ResourceQwenSnapshot(BaseModel):
    provider: str
    display_name: str
    runtime_model: str
    state: str
    running: bool
    ready: bool
    server_url: Optional[str] = None
    ctx_size: int
    max_ctx_size: int
    predict_tokens: int
    threads: int = 0
    threads_batch: int = 0
    cache_ram_mb: int = 0
    pid: Optional[int] = None
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    recent_prompt_tokens_per_second: float = 0.0
    recent_completion_tokens_per_second: float = 0.0
    recent_total_tokens_per_second: float = 0.0
    recent_latency_ms: float = 0.0


class ResourceThermalSnapshot(BaseModel):
    state: str = "unknown"
    rank: int = -1
    source: str = "unavailable"
    captured_at: Optional[datetime] = None
    stale_seconds: Optional[float] = None


class ResourceMonitorResponse(BaseModel):
    captured_at: datetime
    qwen: ResourceQwenSnapshot
    thermal: ResourceThermalSnapshot = Field(default_factory=ResourceThermalSnapshot)
    processes: list[ResourceProcessSnapshot] = Field(default_factory=list)
    backlog: ResourceBacklogSnapshot
    throughput: ResourceThroughputSnapshot
    recent_completions: list[LocalQwenCompletionMetric] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class RuntimeSettingsResponse(BaseModel):
    display_name: str = ""
    llm_provider: str = "openai"
    fake_llm_mode: bool
    llm_model: str
    dashboard_story_llm_enabled: bool
    dashboard_story_model: str
    llm_timeout_seconds: int
    context_summary_limit: int
    rollup_5m_context_summary_limit: int
    rollup_15m_context_summary_limit: int
    rollup_1h_context_summary_limit: int
    rollup_4h_context_summary_limit: int
    window_min_seconds: int
    window_max_seconds: int
    window_token_limit: int
    rollup_5m_raw_token_limit: int
    rollup_5m_enabled: bool
    rollup_15m_enabled: bool
    rollup_1h_enabled: bool
    rollup_4h_enabled: bool
    rollup_1d_enabled: bool
    rollup_1w_enabled: bool
    preferred_local_port: int


class RuntimeSettingsUpdateRequest(BaseModel):
    openai_api_key: Optional[str] = None
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    llm_provider: Optional[Literal["openai", "local_qwen35_4b"]] = None
    fake_llm_mode: Optional[bool] = None
    llm_model: Optional[str] = Field(None, min_length=1, max_length=128)
    dashboard_story_llm_enabled: Optional[bool] = None
    dashboard_story_model: Optional[str] = Field(None, min_length=1, max_length=128)
    llm_timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    rollup_5m_context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    rollup_15m_context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    rollup_1h_context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    rollup_4h_context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    window_min_seconds: Optional[int] = Field(None, ge=10, le=3600)
    window_max_seconds: Optional[int] = Field(None, ge=10, le=3600)
    window_token_limit: Optional[int] = Field(None, ge=100, le=64000)
    rollup_5m_raw_token_limit: Optional[int] = Field(None, ge=0, le=64000)
    rollup_5m_enabled: Optional[bool] = None
    rollup_15m_enabled: Optional[bool] = None
    rollup_1h_enabled: Optional[bool] = None
    rollup_4h_enabled: Optional[bool] = None
    rollup_1d_enabled: Optional[bool] = None
    rollup_1w_enabled: Optional[bool] = None
    preferred_local_port: Optional[int] = Field(None, ge=1024, le=65535)


class LocalModelStatusResponse(BaseModel):
    provider: str
    display_name: str
    runtime_model: str
    prompt_style: str
    state: str
    message: str
    ready: bool = False
    running: bool = False
    server_url: Optional[str] = None
    ctx_size: int
    max_ctx_size: int
    predict_tokens: int
    threads: int = 0
    threads_batch: int = 0
    cache_ram_mb: int = 0
    model_path: Optional[str] = None
    llama_server_path: Optional[str] = None
    cache_root: str
    hf_home: str
    last_error: Optional[str] = None


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    openai_api_key_configured: bool
    openai_api_key_last4: Optional[str] = None
    openai_api_key_storage: str
    runtime_settings: RuntimeSettingsResponse
    local_model: LocalModelStatusResponse
    reanalysis_queued_windows: int = 0
