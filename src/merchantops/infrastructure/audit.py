from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class AuditLog:
    """One JSON line per tool call. Values that could carry PII are not stored."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, default=str, separators=(",", ":")) + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
