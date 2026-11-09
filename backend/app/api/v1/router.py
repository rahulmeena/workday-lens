from __future__ import annotations

from fastapi import APIRouter

from .endpoints import activity, admin, capture, capture_messages, health, policy, resources, setup

router = APIRouter(prefix="/api/v1")
router.include_router(capture.router)
router.include_router(capture_messages.router)
router.include_router(activity.router)
router.include_router(admin.router)
router.include_router(policy.router)
router.include_router(health.router)
router.include_router(resources.router)
router.include_router(setup.router)
