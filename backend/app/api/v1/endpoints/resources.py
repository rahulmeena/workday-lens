from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ....db import get_session
from ....schemas import ResourceMonitorResponse
from ....services.queue import queue, rollup_queue
from ....services.resource_monitor import ResourceMonitorService

router = APIRouter(tags=["resources"])


@router.get("/resources/monitor", response_model=ResourceMonitorResponse)
def resource_monitor(db: Session = Depends(get_session)) -> ResourceMonitorResponse:
    service = ResourceMonitorService(db, queue_depth=queue.qsize() + rollup_queue.qsize())
    return service.snapshot()
