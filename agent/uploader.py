from __future__ import annotations

import asyncio
from asyncio import QueueEmpty

import httpx

from .config import settings
from .local_store import AgentStore, PendingMessage
from .relay import ScreenMessage


class MessageDispatcher:
    def __init__(self, queue: asyncio.Queue[ScreenMessage], store: AgentStore) -> None:
        self.queue = queue
        self.store = store
        self._client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
        self._stop = asyncio.Event()

    async def start(self) -> None:
        while not self._stop.is_set():
            await self._drain_queue()
            await self._sync_pending()
            await asyncio.sleep(settings.flush_interval_seconds)
        await self._drain_queue()
        await self._sync_pending()

    async def stop(self) -> None:
        self._stop.set()
        await self._client.aclose()

    async def _drain_queue(self) -> None:
        try:
            message = await asyncio.wait_for(self.queue.get(), timeout=settings.flush_interval_seconds)
            self._persist(message)
            self.queue.task_done()
        except asyncio.TimeoutError:
            return
        while True:
            try:
                message = self.queue.get_nowait()
            except QueueEmpty:
                break
            self._persist(message)
            self.queue.task_done()

    def _persist(self, message: ScreenMessage) -> None:
        self.store.save_message(settings.session_id, message.source, message.text, message.captured_at)

    async def _sync_pending(self) -> None:
        pending = self.store.load_pending(settings.batch_size)
        if not pending:
            return
        synced_ids: list[int] = []
        for item in pending:
            if await self._send_with_retry(item):
                synced_ids.append(item.id)
            else:
                break
        self.store.mark_synced(synced_ids)

    async def _send_with_retry(self, item: PendingMessage) -> bool:
        delay = 0.5
        for _ in range(settings.max_retry_attempts):
            if await self._send_once(item):
                return True
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)
        return False

    async def _send_once(self, item: PendingMessage) -> bool:
        payload = {
            "session_id": item.session_id,
            "source": item.source,
            "text": item.text,
            "captured_at": item.captured_at.isoformat(),
        }
        try:
            response = await self._client.post(f"{settings.api_base_url}/messages", json=payload)
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
