"""Graceful shutdown with signal handling and cleanup sequencing."""

import asyncio
import signal
from typing import Callable, Awaitable, List
from loguru import logger


class GracefulShutdown:
    def __init__(self):
        self._handlers: List[Callable[[], Awaitable[None]]] = []
        self._shutdown_event = asyncio.Event()

    def register(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register an async cleanup handler."""
        self._handlers.append(handler)

    def setup_signals(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self._trigger()))
            except (NotImplementedError, RuntimeError):
                pass

    async def _trigger(self) -> None:
        if self._shutdown_event.is_set():
            return
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def wait(self) -> None:
        await self._shutdown_event.wait()

    async def run_cleanup(self) -> None:
        logger.info(f"Running {len(self._handlers)} shutdown handlers...")
        for handler in reversed(self._handlers):
            try:
                await asyncio.wait_for(handler(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"Shutdown handler {handler.__name__} timed out")
            except Exception as e:
                logger.error(f"Shutdown handler {handler.__name__} error: {e}")
        logger.info("Graceful shutdown complete")


graceful_shutdown = GracefulShutdown()
