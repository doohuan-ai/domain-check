"""可选：页面加载成功后随机滚动、轻微鼠标移动、随机点击若干可见可点击元素（浅层探索）。

Copyright (c) 2026 doohuan-ai (REEF Jones)
"""

from __future__ import annotations

import asyncio
import random
import time

from playwright.async_api import Error as AsyncPlaywrightError

from syt_dc.config import AppConfig


def _bad_href(href: str | None) -> bool:
    if not href:
        return False
    h = href.strip().lower()
    return h.startswith("javascript:") or h == "#" or h.startswith("mailto:") or h.startswith("tel:")


async def post_goto_random_surfer(page, cfg: AppConfig) -> None:
    """在已打开页面上执行；忽略单项失败；受总预算与点击次数上限约束。"""
    b = cfg.browser
    if not b.random_surfer_enabled:
        return
    deadline = time.monotonic() + max(0.5, b.random_surfer_budget_ms / 1000.0)

    if b.random_surfer_scroll:
        for _ in range(random.randint(1, max(1, b.random_surfer_scroll_passes))):
            if time.monotonic() > deadline:
                break
            try:
                # 混合上下滚动，模拟更自然的浏览行为
                dy = random.randint(120, 520) * (1 if random.random() > 0.2 else -1)
                await page.mouse.wheel(0, dy)
                await asyncio.sleep(random.uniform(0.12, 0.35))
            except Exception:
                break

    vp = page.viewport_size
    if vp and b.random_surfer_mouse_wiggle:
        for _ in range(random.randint(2, 5)):
            if time.monotonic() > deadline:
                break
            try:
                x = random.randint(40, max(41, vp["width"] - 40))
                y = random.randint(40, max(41, vp["height"] - 40))
                await page.mouse.move(x, y, steps=random.randint(4, 12))
                await asyncio.sleep(random.uniform(0.04, 0.12))
            except Exception:
                break

    clicks = 0
    loc = page.locator("a[href], button, [role='button'], input[type='submit'], input[type='button']")
    try:
        n = await loc.count()
    except Exception:
        return
    if n <= 0:
        return
    indices = list(range(min(n, 60)))
    random.shuffle(indices)
    for idx in indices:
        if clicks >= b.random_surfer_max_clicks or time.monotonic() > deadline:
            break
        item = loc.nth(idx)
        try:
            # Playwright Python 的 Locator.is_visible 不接收 timeout 参数。
            if not await item.is_visible():
                continue
            href = await item.get_attribute("href")
            if _bad_href(href):
                continue
            box = await item.bounding_box()
            if not box or box.get("width", 0) < 4 or box.get("height", 0) < 4:
                continue
            # 先 hover 再点击，尽量贴近真实用户行为。
            await item.hover(timeout=2000)
            await asyncio.sleep(random.uniform(0.08, 0.2))
            await item.click(timeout=4000)
            clicks += 1
            await asyncio.sleep(random.uniform(0.25, 0.7))
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
        except Exception:
            continue
