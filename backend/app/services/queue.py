from __future__ import annotations

import asyncio


class WindowQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def put(self, window_id: str) -> None:
        await self._queue.put(window_id)

    def put_nowait(self, window_id: str) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(self._queue.put_nowait, window_id)

    async def get(self) -> str:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()


queue = WindowQueue()
