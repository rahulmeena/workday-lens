from __future__ import annotations

import asyncio
from dataclasses import dataclass
import contextlib
from datetime import datetime, timezone
import json
from typing import Optional


MAX_RELAY_MESSAGE_BYTES = 64 * 1024


@dataclass(slots=True)
class ScreenMessage:
    text: str
    source: Optional[str]
    captured_at: datetime


class ScreenReaderRelay:
    def __init__(self, port: int = 12345, queue: asyncio.Queue[ScreenMessage] | None = None, *, host: str = "127.0.0.1") -> None:
        if queue is None:
            raise ValueError("queue is required")
        self.port = port
        self.host = host
        self.queue = queue
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, host=self.host, port=self.port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await self._read_message(reader)
            if not data:
                return
            raw_text = data.decode("utf-8", errors="ignore").strip()
            event = self._message_from_text(raw_text)
            preview = event.text if len(event.text) <= 500 else f"{event.text[:500]}..."
            print(f"[Relay] Received: {preview}")
            await self.queue.put(event)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _read_message(self, reader: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        remaining = MAX_RELAY_MESSAGE_BYTES
        while remaining > 0:
            chunk = await reader.read(min(4096, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _message_from_text(self, text: str) -> ScreenMessage:
        received_at = datetime.now(timezone.utc)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ScreenMessage(text=text, source=self._source_from_text(text), captured_at=received_at)
        if not isinstance(payload, dict) or payload.get("schema") != "workday_lens_nvda_event.v1":
            return ScreenMessage(text=text, source=self._source_from_text(text), captured_at=received_at)
        event_text = payload.get("text")
        if not isinstance(event_text, str):
            event_text = text
        captured_at = self._captured_at_from_payload(payload) or received_at
        return ScreenMessage(
            text=event_text.strip(),
            source=self._source_from_payload(payload),
            captured_at=captured_at,
        )

    def _captured_at_from_payload(self, payload: dict) -> datetime | None:
        for key in ("captured_at", "generated_at", "timestamp"):
            value = payload.get(key)
            if isinstance(value, str):
                captured_at = self._parse_datetime(value)
                if captured_at is not None:
                    return captured_at
        return None

    def _parse_datetime(self, value: str) -> datetime | None:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _source_from_payload(self, payload: dict) -> str:
        tag = payload.get("tag")
        if isinstance(tag, str) and tag:
            return f"nvda:{tag[:120]}"
        return "nvda:speech"

    def _source_from_text(self, text: str) -> str:
        if text.startswith("[mouse hover"):
            return "nvda:mouse_hover"
        if text.startswith("[mouse action]"):
            return "nvda:mouse_action"
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return "nvda:speech"
        if isinstance(payload, dict) and payload.get("schema") == "workday_lens_nvda_event.v1":
            tag = payload.get("tag")
            if isinstance(tag, str) and tag:
                return f"nvda:{tag[:120]}"
        return "nvda:speech"
