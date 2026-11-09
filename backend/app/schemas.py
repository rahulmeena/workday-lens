from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .models import WindowStatus


class MessageIn(BaseModel):
    session_id: str = Field(..., max_length=64)
    source: Optional[str] = Field(None, max_length=512)
    text: str
    captured_at: datetime


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


class RuntimeSettingsResponse(BaseModel):
    fake_llm_mode: bool
    llm_model: str
    dashboard_story_llm_enabled: bool
    dashboard_story_model: str
    dashboard_story_segment_limit: int
    llm_timeout_seconds: int
    context_summary_limit: int
    window_min_seconds: int
    window_max_seconds: int
    window_token_limit: int
    preferred_local_port: int


class RuntimeSettingsUpdateRequest(BaseModel):
    openai_api_key: Optional[str] = None
    fake_llm_mode: Optional[bool] = None
    llm_model: Optional[str] = Field(None, min_length=1, max_length=128)
    dashboard_story_llm_enabled: Optional[bool] = None
    dashboard_story_model: Optional[str] = Field(None, min_length=1, max_length=128)
    dashboard_story_segment_limit: Optional[int] = Field(None, ge=1, le=96)
    llm_timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    context_summary_limit: Optional[int] = Field(None, ge=0, le=50)
    window_min_seconds: Optional[int] = Field(None, ge=10, le=3600)
    window_max_seconds: Optional[int] = Field(None, ge=10, le=3600)
    window_token_limit: Optional[int] = Field(None, ge=100, le=20000)
    preferred_local_port: Optional[int] = Field(None, ge=1024, le=65535)


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    openai_api_key_configured: bool
    openai_api_key_last4: Optional[str] = None
    openai_api_key_storage: str
    runtime_settings: RuntimeSettingsResponse
    reanalysis_queued_windows: int = 0
