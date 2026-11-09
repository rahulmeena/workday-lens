from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ....db import get_session
from ....models import WindowStatus
from ....schemas import ActivityDashboardResponse, PaginatedResponse
from ....services.window import WindowReadService

router = APIRouter(tags=["activity"])


@router.get("/employee/activity", response_model=PaginatedResponse)
def get_activity(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    status: WindowStatus | None = Query(None),
    db: Session = Depends(get_session),
) -> PaginatedResponse:
    service = WindowReadService(db)
    return service.employee_activity(limit=limit, cursor=cursor, status=status)


@router.get("/activity/dashboard", response_model=ActivityDashboardResponse)
def get_activity_dashboard(
    day: date | None = Query(None),
    db: Session = Depends(get_session),
) -> ActivityDashboardResponse:
    service = WindowReadService(db)
    return service.activity_dashboard(day=day)
