from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ....db import get_session
from ....schemas import ViolationListResponse, WindowDetailResponse
from ....services.window import WindowReadService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/violations", response_model=ViolationListResponse)
def list_violations(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    db: Session = Depends(get_session),
) -> ViolationListResponse:
    service = WindowReadService(db)
    return service.violation_feed(limit=limit, cursor=cursor)


@router.get("/windows/{window_id}", response_model=WindowDetailResponse)
def window_detail(window_id: str, db: Session = Depends(get_session)) -> WindowDetailResponse:
    service = WindowReadService(db)
    try:
        return service.window_detail(window_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
