from __future__ import annotations

import asyncio
import signal

from .runtime import AgentRuntime


async def _run() -> None:
    runtime = AgentRuntime()
    await runtime.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())
    await stop_event.wait()

    await runtime.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
