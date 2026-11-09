from __future__ import annotations

import asyncio


class WindowQueue:
    def __init__(self) -> None:
        # Keep fresh capture windows responsive even when old backlog exists.
        self._queue: asyncio.LifoQueue[str] = asyncio.LifoQueue()

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
rollup_queue = WindowQueue()
