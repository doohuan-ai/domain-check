"""运行期辅助：异步截图总字节预算（防磁盘打满）。

Copyright (c) 2026 doohuan-ai (REEF Jones)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScreenshotBudgetAsync:
    """限制单次巡检写入的截图总大小；超过预算则跳过后续截图（仍完成 URL 检测）。"""

    max_total_bytes: int
    _used: int = 0
    _skipped: int = 0
    _exhausted_notified: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def used_bytes(self) -> int:
        return self._used

    @property
    def skipped_count(self) -> int:
        return self._skipped

    @property
    def is_limited(self) -> bool:
        return self.max_total_bytes > 0

    def summary_line(self) -> str | None:
        """预算用尽或存在跳过时返回一行说明，供终端提示。"""
        if not self.is_limited:
            return None
        if self._skipped <= 0:
            return None
        mb_cap = self.max_total_bytes / (1024 * 1024)
        mb_used = self._used / (1024 * 1024)
        return (
            f"截图总大小已达上限（{mb_cap:.0f} MB，已写入约 {mb_used:.1f} MB），"
            f"后续 {self._skipped} 次截图已跳过（检测与状态码不受影响）。"
            f"可在配置 output.max_total_screenshot_bytes 调大或设为 0 表示不限制。"
        )

    async def allow_shot(self, estimate_bytes: int = 600_000) -> bool:
        if self.max_total_bytes <= 0:
            return True
        async with self._lock:
            ok = self._used + estimate_bytes <= self.max_total_bytes
            if not ok:
                self._skipped += 1
            return ok

    async def record_file(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        async with self._lock:
            self._used += path.stat().st_size
