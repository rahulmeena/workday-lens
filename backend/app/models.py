from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    ADMIN = "admin"


class WindowStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    VIOLATION = "violation"
    PENDING_LLM = "pending_llm"


class EventType(str, enum.Enum):
    VIOLATION = "violation"


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    examples_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Window(Base):
    __tablename__ = "windows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[WindowStatus] = mapped_column(Enum(WindowStatus), nullable=False, default=WindowStatus.QUEUED)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list['Message']] = relationship("Message", back_populates="window")
    runs: Mapped[list['LLMRun']] = relationship("LLMRun", back_populates="window")
    events: Mapped[list['Event']] = relationship("Event", back_populates="window")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("windows.id"), nullable=True, index=True)

    window: Mapped[Window | None] = relationship("Window", back_populates="messages")


class LLMRun(Base):
    __tablename__ = "llm_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    window_id: Mapped[str] = mapped_column(String(36), ForeignKey("windows.id"), nullable=False, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[WindowStatus] = mapped_column(Enum(WindowStatus), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # store percentage * 100
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    window: Mapped[Window] = relationship("Window", back_populates="runs")


class ActivityRollup(Base):
    __tablename__ = "activity_rollups"
    __table_args__ = (
        UniqueConstraint("level", "started_at", "ended_at", name="uq_activity_rollup_level_range"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    level: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    status: Mapped[WindowStatus] = mapped_column(Enum(WindowStatus), nullable=False, default=WindowStatus.QUEUED)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActivityGanttCache(Base):
    __tablename__ = "activity_gantt_cache"
    __table_args__ = (
        UniqueConstraint("mode", "started_at", "ended_at", name="uq_activity_gantt_cache_mode_range"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    mode: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    source_signature: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processed")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("window_id", "type", name="uq_event_window_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    window_id: Mapped[str] = mapped_column(String(36), ForeignKey("windows.id"), nullable=False, index=True)
    type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    window: Mapped[Window] = relationship("Window", back_populates="events")
