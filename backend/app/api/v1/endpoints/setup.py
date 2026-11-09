from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ....core.config import RuntimeSettings, settings
from ....core.time import local_today
from ....db import get_session
from ....schemas import RuntimeSettingsResponse, RuntimeSettingsUpdateRequest, SetupStatusResponse
from ....services.llm import llm_service
from ....services.queue import queue
from ....services.window import WindowReanalysisService

router = APIRouter(prefix="/setup", tags=["setup"])


def _runtime_settings_response(runtime: RuntimeSettings) -> RuntimeSettingsResponse:
    return RuntimeSettingsResponse(
        fake_llm_mode=runtime.fake_llm_mode,
        llm_model=runtime.llm_model,
        dashboard_story_llm_enabled=runtime.dashboard_story_llm_enabled,
        dashboard_story_model=runtime.dashboard_story_model,
        dashboard_story_segment_limit=runtime.dashboard_story_segment_limit,
        llm_timeout_seconds=runtime.llm_timeout_seconds,
        context_summary_limit=runtime.context_summary_limit,
        window_min_seconds=runtime.window_min_seconds,
        window_max_seconds=runtime.window_max_seconds,
        window_token_limit=runtime.window_token_limit,
        preferred_local_port=runtime.preferred_local_port,
    )


def _setup_status(runtime: RuntimeSettings, reanalysis_queued_windows: int = 0) -> SetupStatusResponse:
    key_configured = settings.openai_api_key_configured()
    needs_setup = not runtime.fake_llm_mode and not key_configured
    return SetupStatusResponse(
        needs_setup=needs_setup,
        openai_api_key_configured=key_configured,
        openai_api_key_last4=settings.openai_api_key_last4(),
        openai_api_key_storage=settings.openai_api_key_storage,
        runtime_settings=_runtime_settings_response(runtime),
        reanalysis_queued_windows=reanalysis_queued_windows,
    )


@router.get("/status", response_model=SetupStatusResponse)
def get_setup_status() -> SetupStatusResponse:
    return _setup_status(settings.runtime())


@router.put("/config", response_model=SetupStatusResponse)
def update_runtime_settings(payload: RuntimeSettingsUpdateRequest) -> SetupStatusResponse:
    updates: dict[str, object] = {}
    if payload.openai_api_key is not None:
        openai_api_key = payload.openai_api_key.strip()
        if not openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="OpenAI API key cannot be empty.",
            )
        updates["openai_api_key"] = openai_api_key
    if payload.fake_llm_mode is not None:
        updates["fake_llm_mode"] = payload.fake_llm_mode
    if payload.llm_model is not None:
        updates["llm_model"] = payload.llm_model.strip()
    if payload.dashboard_story_llm_enabled is not None:
        updates["dashboard_story_llm_enabled"] = payload.dashboard_story_llm_enabled
    if payload.dashboard_story_model is not None:
        updates["dashboard_story_model"] = payload.dashboard_story_model.strip()
    if payload.dashboard_story_segment_limit is not None:
        updates["dashboard_story_segment_limit"] = payload.dashboard_story_segment_limit
    if payload.llm_timeout_seconds is not None:
        updates["llm_timeout_seconds"] = payload.llm_timeout_seconds
    if payload.context_summary_limit is not None:
        updates["context_summary_limit"] = payload.context_summary_limit
    if payload.window_min_seconds is not None:
        updates["window_min_seconds"] = payload.window_min_seconds
    if payload.window_max_seconds is not None:
        updates["window_max_seconds"] = payload.window_max_seconds
    if payload.window_token_limit is not None:
        updates["window_token_limit"] = payload.window_token_limit
    if payload.preferred_local_port is not None:
        updates["preferred_local_port"] = payload.preferred_local_port

    current = settings.runtime()
    next_min = int(updates.get("window_min_seconds", current.window_min_seconds))
    next_max = int(updates.get("window_max_seconds", current.window_max_seconds))
    if next_max < next_min:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Window max seconds must be greater than or equal to window min seconds.",
        )

    runtime = settings.update_runtime(**updates) if updates else current
    llm_service.reload_from_settings()
    return _setup_status(runtime)


@router.post("/reprocess-today", response_model=SetupStatusResponse)
async def reprocess_today(db: Session = Depends(get_session)) -> SetupStatusResponse:
    runtime = settings.runtime()
    if not runtime.fake_llm_mode and not settings.openai_api_key_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configure an OpenAI API key or enable fake mode before reprocessing today's activity.",
        )
    queued_window_ids = WindowReanalysisService(db).queue_day(local_today())
    db.commit()
    for window_id in queued_window_ids:
        await queue.put(window_id)
    return _setup_status(runtime, reanalysis_queued_windows=len(queued_window_ids))


@router.delete("/api-key", response_model=SetupStatusResponse)
def delete_openai_api_key() -> SetupStatusResponse:
    runtime = settings.delete_openai_api_key()
    llm_service.reload_from_settings()
    return _setup_status(runtime)
