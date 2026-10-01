from __future__ import annotations

import time
from datetime import datetime, timezone


class Clock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock(Clock):
    def __init__(self, start: float = 0.0) -> None:
        self._mono = start

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._mono += seconds
