from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ....db import get_session
from ....schemas import PolicyCreateRequest, PolicyResponse, PolicyUpdateRequest
from ....services.window import PolicyService

router = APIRouter(prefix="/policy", tags=["policy"])


def _serialize_response(policy) -> PolicyResponse:
    examples = [line.strip() for line in (policy.examples_json or "").splitlines() if line.strip()]
    return PolicyResponse(
        id=policy.id,
        text=policy.text,
        examples=examples,
        active=policy.active,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.get("", response_model=list[PolicyResponse])
def list_policies(db: Session = Depends(get_session)) -> list[PolicyResponse]:
    service = PolicyService(db)
    policies = service.list_policies()
    return [_serialize_response(policy) for policy in policies]


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyCreateRequest, db: Session = Depends(get_session)) -> PolicyResponse:
    service = PolicyService(db)
    policy = service.create_policy(payload.text, payload.examples)
    db.commit()
    return _serialize_response(policy)


@router.put("/{policy_id}", response_model=PolicyResponse)
def update_policy(policy_id: str, payload: PolicyUpdateRequest, db: Session = Depends(get_session)) -> PolicyResponse:
    service = PolicyService(db)
    try:
        policy = service.update_policy(policy_id, payload.text, payload.examples, payload.active)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return _serialize_response(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def archive_policy(policy_id: str, db: Session = Depends(get_session)) -> Response:
    service = PolicyService(db)
    if not service.archive_policy(policy_id):
        raise HTTPException(status_code=404, detail="Policy not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
