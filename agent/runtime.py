from __future__ import annotations

import asyncio
from pathlib import Path

from .config import settings
from .local_store import AgentStore
from .relay import ScreenMessage, ScreenReaderRelay
from .uploader import MessageDispatcher


class AgentRuntime:
    def __init__(
        self,
        store_path: Path | None = None,
        *,
        queue_maxsize: int = 1000,
        api_base_url: str | None = None,
    ) -> None:
        self._queue: asyncio.Queue[ScreenMessage] = asyncio.Queue(maxsize=queue_maxsize)
        self._store = AgentStore(store_path or Path(settings.store_path))
        self._relay = ScreenReaderRelay(settings.screen_reader_port, self._queue, host=settings.screen_reader_host)
        self._dispatcher = MessageDispatcher(self._queue, self._store, api_base_url=api_base_url)
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        await self._relay.start()
        self._dispatcher_task = asyncio.create_task(self._dispatcher.start())
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self._relay.stop()
        await self._dispatcher.stop()
        if self._dispatcher_task is not None:
            await self._dispatcher_task
            self._dispatcher_task = None
        self._started = False
