from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from merchantops.infrastructure.clock import Clock

T = TypeVar("T")


class TtlCache:
    """Short TTL cache plus in-flight de-duplication for identical GETs."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._data: dict[str, tuple[object, float]] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _fresh(self, key: str) -> object | None:
        found = self._data.get(key)
        if found is None:
            return None
        value, expires = found
        if self.clock.monotonic() >= expires:
            self._data.pop(key, None)
            return None
        return value

    async def get_or_set(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[T]],
    ) -> tuple[T, bool]:
        async with self._lock:
            cached = self._fresh(key)
            if cached is not None:
                return cached, True  # type: ignore[return-value]
            future = self._inflight.get(key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                leader = True
            else:
                leader = False
        if not leader:
            return await future, True
        try:
            value = await factory()
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            async with self._lock:
                self._inflight.pop(key, None)
            raise
        async with self._lock:
            self._data[key] = (value, self.clock.monotonic() + ttl)
            self._inflight.pop(key, None)
        if not future.done():
            future.set_result(value)
        return value, False
