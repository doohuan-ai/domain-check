"""运行期辅助：异步截图总字节预算（防磁盘打满）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScreenshotBudgetAsync:
    """限制单次巡检写入的截图总大小；超过预算则跳过后续截图（仍完成 URL 检测）。"""

    max_total_bytes: int
    _used: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def allow_shot(self, estimate_bytes: int = 600_000) -> bool:
        if self.max_total_bytes <= 0:
            return True
        async with self._lock:
            return self._used + estimate_bytes <= self.max_total_bytes

    async def record_file(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        async with self._lock:
            self._used += path.stat().st_size
