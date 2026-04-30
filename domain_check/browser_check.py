"""Playwright：打开 URL、基于 HTTP/DOM 判定可达性；视口截图；支持异步多标签分批与重试。

Copyright (c) 2026 doohuan-ai (REEF Jones)
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from playwright.async_api import Error as AsyncPlaywrightError
from playwright.async_api import TimeoutError as AsyncPlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from domain_check.browser_launch import (
    automation_cleanup_init_script,
    build_context_options,
    launch_google_chrome_async,
    launch_google_chrome_sync,
)
from domain_check.config import AppConfig
from domain_check.precheck_net import run_url_precheck
from domain_check.random_surfer import post_goto_random_surfer
from domain_check.run_support import ScreenshotBudgetAsync


def _compact_error_message(err: str) -> str:
    """
    压缩 Playwright 错误文本，避免重复段与超长 Call log 淹没 Excel。
    保留第一段核心错误原因。
    """
    raw = (err or "").replace("\r\n", "\n").strip()
    if not raw:
        return "未知错误"
    first_block = raw.split("\n\n", 1)[0].strip()
    lines = [ln.rstrip() for ln in first_block.split("\n") if ln.strip()]
    if not lines:
        return "未知错误"
    return " | ".join(lines)


def results_when_nat_skipped(urls: list[str], exc: BaseException) -> list[UrlCheckResult]:
    """路由器 SSH/NAT 失败且策略为跳过本出口时，为每个 URL 写入占位结果（未启动浏览器）。"""
    detail = f"{type(exc).__name__}: {exc}"
    summary = "SSH/NAT 切换失败，未测此 URL（浏览器未启动）"
    return [
        UrlCheckResult(
            ok=False,
            label="skipped",
            summary=summary,
            status_code=None,
            final_url=None,
            error_message=detail,
            screenshot_path=None,
            line_health="未检测",
            precheck_detail="未执行（NAT/SSH 失败）",
            precheck_state="off",
        )
        for _ in urls
    ]


@dataclass
class UrlCheckResult:
    ok: bool
    label: str
    summary: str
    status_code: int | None
    final_url: str | None
    error_message: str | None
    screenshot_path: str | None
    line_health: str = "未检测"
    precheck_detail: str = "关闭"
    precheck_state: str = "off"


_ALLOWED_WAIT = frozenset({"load", "domcontentloaded", "networkidle", "commit"})


def _normalize_wait_until(raw: str) -> str:
    w = (raw or "domcontentloaded").strip().lower()
    if w not in _ALLOWED_WAIT:
        return "domcontentloaded"
    return w


def _apply_context_init_scripts_sync(context, cfg: AppConfig) -> None:
    if cfg.browser.inject_automation_cleanup_script:
        context.add_init_script(automation_cleanup_init_script())


async def _apply_context_init_scripts_async(context, cfg: AppConfig) -> None:
    if cfg.browser.inject_automation_cleanup_script:
        await context.add_init_script(automation_cleanup_init_script())


def _new_context(browser, cfg: AppConfig):
    context = browser.new_context(**build_context_options(cfg))
    _apply_context_init_scripts_sync(context, cfg)
    return context


async def _new_context_async(browser, cfg: AppConfig):
    context = await browser.new_context(**build_context_options(cfg))
    await _apply_context_init_scripts_async(context, cfg)
    return context


def _body_text_sample(page, max_chars: int) -> str:
    try:
        t = page.inner_text("body", timeout=5_000)
    except PlaywrightError:
        return ""
    if not t:
        return ""
    return t[:max_chars].lower()


async def _async_body_text_sample(page, max_chars: int) -> str:
    try:
        t = await page.inner_text("body", timeout=5_000)
    except AsyncPlaywrightError:
        return ""
    if not t:
        return ""
    return t[:max_chars].lower()


def _match_block_keywords(text: str, keywords: list[str]) -> str | None:
    for kw in keywords:
        k = kw.lower().strip()
        if k and k in text:
            return kw
    return None


_CAPTCHA_FALLBACK_KEYWORDS = [
    "prove your humanity",
    "i'm not a robot",
    "recaptcha",
    "hcaptcha",
    "cf-chl",
    "attention required",
]


def _captcha_hit_from_text(sample: str, user_keywords: list[str]) -> str | None:
    """先匹配用户关键词，再匹配内置验证码兜底关键词。"""
    hit = _match_block_keywords(sample, user_keywords)
    if hit:
        return hit
    return _match_block_keywords(sample, _CAPTCHA_FALLBACK_KEYWORDS)


def _sync_captcha_hit(page, cfg: AppConfig) -> str | None:
    acfg = cfg.access
    body = _body_text_sample(page, acfg.body_text_max_chars)
    title = ""
    try:
        title = (page.title() or "").lower()
    except PlaywrightError:
        pass
    url = (page.url or "").lower()
    sample = "\n".join([body, title, url])
    return _captcha_hit_from_text(sample, acfg.captcha_keywords)


async def _async_captcha_hit(page, cfg: AppConfig) -> str | None:
    acfg = cfg.access
    body = await _async_body_text_sample(page, acfg.body_text_max_chars)
    title = ""
    try:
        title = (await page.title() or "").lower()
    except AsyncPlaywrightError:
        pass
    url = (page.url or "").lower()
    sample = "\n".join([body, title, url])
    return _captcha_hit_from_text(sample, acfg.captcha_keywords)


def _shot_sync(page, path: Path | None) -> None:
    if not path:
        return
    try:
        page.screenshot(path=str(path), full_page=False)
    except PlaywrightError:
        pass


async def _shot_async(
    page,
    path: Path | None,
    *,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
) -> None:
    if not path:
        return
    if screenshot_budget is not None and not await screenshot_budget.allow_shot():
        return
    try:
        await page.screenshot(path=str(path), full_page=False)
        if screenshot_budget is not None:
            await screenshot_budget.record_file(path)
    except AsyncPlaywrightError:
        pass


def _sync_post_goto_settle(page, cfg: AppConfig) -> None:
    """
    导航返回后：可选再等 load 事件，再固定休眠若干毫秒，减轻 SPA 仅出现转圈就截图的问题。
    """
    bcfg = cfg.browser
    if bcfg.post_goto_try_load_state:
        try:
            page.wait_for_load_state("load", timeout=bcfg.post_goto_load_state_timeout_ms)
        except PlaywrightError:
            pass
    if bcfg.post_goto_settle_ms > 0:
        time.sleep(bcfg.post_goto_settle_ms / 1000.0)


async def _async_post_goto_settle(page, cfg: AppConfig) -> None:
    bcfg = cfg.browser
    if bcfg.post_goto_try_load_state:
        try:
            await page.wait_for_load_state("load", timeout=bcfg.post_goto_load_state_timeout_ms)
        except AsyncPlaywrightError:
            pass
    if bcfg.post_goto_settle_ms > 0:
        await asyncio.sleep(bcfg.post_goto_settle_ms / 1000.0)


def check_url_with_page(page, url: str, cfg: AppConfig, screenshot_path: Path | None) -> UrlCheckResult:
    bcfg = cfg.browser
    acfg = cfg.access
    wait_until = _normalize_wait_until(bcfg.wait_until)
    timeout = bcfg.goto_timeout_ms

    status_code: int | None = None
    final_url: str | None = None
    err_msg: str | None = None

    try:
        response = page.goto(url, wait_until=wait_until, timeout=timeout)
    except PlaywrightTimeoutError as e:
        err_msg = _compact_error_message(str(e) or "timeout")
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"超时: {err_msg}",
            status_code=None,
            final_url=page.url,
            error_message=err_msg,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )
    except PlaywrightError as e:
        err_msg = _compact_error_message(str(e) or "playwright_error")
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"导航失败: {err_msg}",
            status_code=None,
            final_url=None,
            error_message=err_msg,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    _sync_post_goto_settle(page, cfg)

    final_url = page.url
    if response is not None:
        status_code = response.status

    if status_code is None:
        summary = "无 HTTP 响应（可能是非文档导航）"
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=summary,
            status_code=None,
            final_url=final_url,
            error_message=summary,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code == 403 or status_code == 451:
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="blocked",
            summary=f"HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=None,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code >= 400:
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=f"HTTP {status_code}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code < 200 or status_code >= 300:
        _shot_sync(page, screenshot_path)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"非成功状态: HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=f"HTTP {status_code}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if 200 <= status_code < 300:
        cap_hit = _sync_captcha_hit(page, cfg)
        if cap_hit:
            _shot_sync(page, screenshot_path)
            return UrlCheckResult(
                ok=False,
                label="challenge",
                summary=f"疑似人机验证: {cap_hit}",
                status_code=status_code,
                final_url=final_url,
                error_message=None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

    if acfg.enable_body_keyword_check:
        sample = _body_text_sample(page, acfg.body_text_max_chars)
        hit = _match_block_keywords(sample, acfg.block_keywords)
        if hit:
            _shot_sync(page, screenshot_path)
            return UrlCheckResult(
                ok=False,
                label="blocked",
                summary=f"正文命中关键词: {hit}",
                status_code=status_code,
                final_url=final_url,
                error_message=None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

    shot: str | None = None
    if bcfg.screenshot_on_success and screenshot_path:
        try:
            page.screenshot(path=str(screenshot_path), full_page=False)
            shot = str(screenshot_path)
        except PlaywrightError:
            shot = None

    return UrlCheckResult(
        ok=True,
        label="success",
        summary=f"HTTP {status_code}",
        status_code=status_code,
        final_url=final_url,
        error_message=None,
        screenshot_path=shot,
    )


async def classify_after_goto_async(
    page,
    response,
    cfg: AppConfig,
    screenshot_path: Path | None,
    *,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
) -> UrlCheckResult:
    """goto 已成功返回 response 后的分类（含重定向后的 final URL 与最终文档 HTTP 状态）。"""
    await _async_post_goto_settle(page, cfg)

    bcfg = cfg.browser
    acfg = cfg.access
    final_url = page.url
    status_code: int | None = response.status if response is not None else None

    if status_code is None:
        summary = "无 HTTP 响应（可能是非文档导航）"
        await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=summary,
            status_code=None,
            final_url=final_url,
            error_message=summary,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code == 403 or status_code == 451:
        await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
        return UrlCheckResult(
            ok=False,
            label="blocked",
            summary=f"HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=None,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code >= 400:
        await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=f"HTTP {status_code}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if status_code < 200 or status_code >= 300:
        await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"非成功状态: HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=f"HTTP {status_code}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if 200 <= status_code < 300:
        cap_hit = await _async_captcha_hit(page, cfg)
        if cap_hit:
            await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
            return UrlCheckResult(
                ok=False,
                label="challenge",
                summary=f"疑似人机验证: {cap_hit}",
                status_code=status_code,
                final_url=final_url,
                error_message=None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

    if acfg.enable_body_keyword_check:
        sample = await _async_body_text_sample(page, acfg.body_text_max_chars)
        hit = _match_block_keywords(sample, acfg.block_keywords)
        if hit:
            await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
            return UrlCheckResult(
                ok=False,
                label="blocked",
                summary=f"正文命中关键词: {hit}",
                status_code=status_code,
                final_url=final_url,
                error_message=None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

    shot: str | None = None
    if (
        bcfg.screenshot_on_success
        and screenshot_path
        and bcfg.random_surfer_enabled
        and bcfg.random_surfer_screenshot_before_actions
    ):
        if screenshot_budget is None or await screenshot_budget.allow_shot():
            try:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                shot = str(screenshot_path)
                if screenshot_budget is not None:
                    await screenshot_budget.record_file(screenshot_path)
            except AsyncPlaywrightError:
                shot = None

    if bcfg.random_surfer_enabled:
        try:
            await post_goto_random_surfer(page, cfg)
        except Exception:
            pass

    if bcfg.screenshot_on_success and screenshot_path and not shot:
        if screenshot_budget is None or await screenshot_budget.allow_shot():
            try:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                shot = str(screenshot_path)
                if screenshot_budget is not None:
                    await screenshot_budget.record_file(screenshot_path)
            except AsyncPlaywrightError:
                shot = None

    return UrlCheckResult(
        ok=True,
        label="success",
        summary=f"HTTP {status_code}",
        status_code=status_code,
        final_url=final_url,
        error_message=None,
        screenshot_path=shot,
    )


def _emit_browser_event(
    event_log: Callable[[dict[str, Any]], None] | None,
    run_meta: dict[str, Any] | None,
    url: str,
    url_index: int,
    payload: dict[str, Any],
) -> None:
    if not event_log:
        return
    base: dict[str, Any] = {**(run_meta or {}), "url": url, "url_index": url_index}
    base.update(payload)
    event_log(base)


async def _check_one_url_async(
    context,
    url: str,
    cfg: AppConfig,
    screenshot_path: Path | None,
    *,
    initial_delay_s: float = 0.0,
    url_index: int = 0,
    event_log: Callable[[dict[str, Any]], None] | None = None,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
    run_meta: dict[str, Any] | None = None,
) -> UrlCheckResult:
    """单 URL：网络类与内容类重试分层；成功 / 验证墙 / 关键词命中即停止。"""
    bcfg = cfg.browser
    wait_until = _normalize_wait_until(bcfg.wait_until)
    timeout = bcfg.goto_timeout_ms
    net_max = bcfg.navigation_network_max_attempts
    cont_max = bcfg.navigation_content_max_attempts
    net_delay_s = bcfg.navigation_network_retry_delay_ms / 1000.0
    net_backoff = max(1.0, bcfg.navigation_network_retry_backoff)
    cont_delay_s = bcfg.navigation_content_retry_delay_ms / 1000.0
    pre = await asyncio.to_thread(run_url_precheck, url, cfg)

    def _with_precheck(res: UrlCheckResult) -> UrlCheckResult:
        res.line_health = pre.line_health
        res.precheck_detail = pre.detail
        res.precheck_state = pre.state
        return res

    page = await context.new_page()
    try:
        if initial_delay_s > 0:
            await asyncio.sleep(initial_delay_s)
        _emit_browser_event(
            event_log,
            run_meta,
            url,
            url_index,
            {
                "phase": "url_start",
                "network_max": net_max,
                "content_max": cont_max,
                "precheck_state": pre.state,
                "line_health": pre.line_health,
            },
        )

        for content_try in range(cont_max):
            response = None
            for net_try in range(net_max):
                try:
                    response = await page.goto(url, wait_until=wait_until, timeout=timeout)
                    break
                except AsyncPlaywrightTimeoutError as e:
                    err_msg = _compact_error_message(str(e) or "timeout")
                    await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
                    last = UrlCheckResult(
                        ok=False,
                        label="error",
                        summary=f"超时: {err_msg}",
                        status_code=None,
                        final_url=page.url,
                        error_message=err_msg,
                        screenshot_path=str(screenshot_path) if screenshot_path else None,
                    )
                    _emit_browser_event(
                        event_log,
                        run_meta,
                        url,
                        url_index,
                        {
                            "phase": "goto_timeout",
                            "network_try": net_try + 1,
                            "content_try": content_try + 1,
                            "error": err_msg,
                        },
                    )
                    if net_try < net_max - 1:
                        delay = net_delay_s * (net_backoff**net_try)
                        await asyncio.sleep(delay)
                        continue
                    _emit_browser_event(
                        event_log,
                        run_meta,
                        url,
                        url_index,
                        {"phase": "url_end", "label": last.label, "reason": "network_exhausted"},
                    )
                    return _with_precheck(last)
                except AsyncPlaywrightError as e:
                    err_msg = _compact_error_message(str(e) or "playwright_error")
                    await _shot_async(page, screenshot_path, screenshot_budget=screenshot_budget)
                    last = UrlCheckResult(
                        ok=False,
                        label="error",
                        summary=f"导航失败: {err_msg}",
                        status_code=None,
                        final_url=None,
                        error_message=err_msg,
                        screenshot_path=str(screenshot_path) if screenshot_path else None,
                    )
                    _emit_browser_event(
                        event_log,
                        run_meta,
                        url,
                        url_index,
                        {
                            "phase": "goto_error",
                            "network_try": net_try + 1,
                            "content_try": content_try + 1,
                            "error": err_msg,
                        },
                    )
                    if net_try < net_max - 1:
                        delay = net_delay_s * (net_backoff**net_try)
                        await asyncio.sleep(delay)
                        continue
                    _emit_browser_event(
                        event_log,
                        run_meta,
                        url,
                        url_index,
                        {"phase": "url_end", "label": last.label, "reason": "network_exhausted"},
                    )
                    return _with_precheck(last)

            if response is None:
                return _with_precheck(
                    UrlCheckResult(
                    ok=False,
                    label="error",
                    summary="未知状态（无响应）",
                    status_code=None,
                    final_url=None,
                    error_message="未知状态",
                    screenshot_path=None,
                    )
                )

            last = await classify_after_goto_async(
                page,
                response,
                cfg,
                screenshot_path,
                screenshot_budget=screenshot_budget,
            )
            _emit_browser_event(
                event_log,
                run_meta,
                url,
                url_index,
                {
                    "phase": "classified",
                    "content_try": content_try + 1,
                    "label": last.label,
                    "status_code": last.status_code,
                },
            )
            if last.label in ("success", "blocked", "challenge"):
                _emit_browser_event(
                    event_log,
                    run_meta,
                    url,
                    url_index,
                    {"phase": "url_end", "label": last.label},
                )
                return _with_precheck(last)
            if last.label == "error" and content_try < cont_max - 1:
                _emit_browser_event(
                    event_log,
                    run_meta,
                    url,
                    url_index,
                    {"phase": "content_retry", "sleep_s": cont_delay_s},
                )
                await asyncio.sleep(cont_delay_s)
                continue
            _emit_browser_event(
                event_log,
                run_meta,
                url,
                url_index,
                {"phase": "url_end", "label": last.label, "reason": "content_exhausted_or_error"},
            )
            return _with_precheck(last)

        return _with_precheck(
            UrlCheckResult(
            ok=False,
            label="error",
            summary="未知状态",
            status_code=None,
            final_url=None,
            error_message="未知状态",
            screenshot_path=None,
            )
        )
    finally:
        await page.close()


def _batch_size_for(cfg: AppConfig, n_urls: int) -> int:
    bcfg = cfg.browser
    raw = bcfg.tabs_batch_size
    if raw <= 0:
        batch = n_urls if n_urls > 0 else 1
    else:
        batch = max(1, min(raw, n_urls)) if n_urls else 1
    cap = bcfg.max_concurrent_tabs
    if cap > 0 and n_urls > 0:
        batch = max(1, min(batch, cap, n_urls))
    return batch


async def check_urls_in_batches_async(
    context,
    urls: list[str],
    cfg: AppConfig,
    screenshot_paths: list[Path | None],
    *,
    event_log: Callable[[dict[str, Any]], None] | None = None,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
    run_meta: dict[str, Any] | None = None,
) -> list[UrlCheckResult]:
    """
    按 tabs_batch_size 分批：每批内多标签并行导航并各自重试；
    批次之间间隔 tabs_batch_delay_ms。tabs_batch_size 为 0 时一批内打开全部 URL。
    同批内各任务按 tab_stagger_ms 递增延迟再发起 goto，缓和瞬时并发。
    """
    n = len(urls)
    if n == 0:
        return []
    if len(screenshot_paths) != n:
        raise ValueError("screenshot_paths 长度须与 urls 一致")

    batch = _batch_size_for(cfg, n)
    delay_s = cfg.browser.tabs_batch_delay_ms / 1000.0
    stagger_s = cfg.browser.tab_stagger_ms / 1000.0
    results: list[UrlCheckResult] = []

    for start in range(0, n, batch):
        end = min(start + batch, n)
        tasks = [
            _check_one_url_async(
                context,
                urls[i],
                cfg,
                screenshot_paths[i],
                initial_delay_s=(i - start) * stagger_s,
                url_index=i + 1,
                event_log=event_log,
                screenshot_budget=screenshot_budget,
                run_meta=run_meta,
            )
            for i in range(start, end)
        ]
        chunk = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in zip(range(start, end), chunk):
            if isinstance(r, Exception):
                results.append(
                    UrlCheckResult(
                        ok=False,
                        label="error",
                        summary=f"任务异常: {type(r).__name__}",
                        status_code=None,
                        final_url=None,
                        error_message=str(r),
                        screenshot_path=str(screenshot_paths[i]) if screenshot_paths[i] else None,
                    )
                )
            else:
                results.append(r)
        if end < n and delay_s > 0:
            await asyncio.sleep(delay_s)

    return results


async def run_urls_with_async_browser(
    cfg: AppConfig,
    urls: list[str],
    screenshot_paths: list[Path | None],
    *,
    event_log: Callable[[dict[str, Any]], None] | None = None,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
    run_meta: dict[str, Any] | None = None,
) -> list[UrlCheckResult]:
    """启动一次浏览器 + 一个 Context，分批并行检测全部 URL。"""
    async with async_playwright() as p:
        browser = await launch_google_chrome_async(p, cfg)
        try:
            context = await _new_context_async(browser, cfg)
            try:
                return await check_urls_in_batches_async(
                    context,
                    urls,
                    cfg,
                    screenshot_paths,
                    event_log=event_log,
                    screenshot_budget=screenshot_budget,
                    run_meta=run_meta,
                )
            finally:
                await context.close()
        finally:
            await browser.close()


def run_urls_with_async_browser_sync(
    cfg: AppConfig,
    urls: list[str],
    screenshot_paths: list[Path | None],
    *,
    event_log: Callable[[dict[str, Any]], None] | None = None,
    screenshot_budget: ScreenshotBudgetAsync | None = None,
    run_meta: dict[str, Any] | None = None,
) -> list[UrlCheckResult]:
    """同步封装：内部 asyncio.run，供 runner 调用。"""
    return asyncio.run(
        run_urls_with_async_browser(
            cfg,
            urls,
            screenshot_paths,
            event_log=event_log,
            screenshot_budget=screenshot_budget,
            run_meta=run_meta,
        )
    )


def check_url(url: str, cfg: AppConfig, screenshot_path: Path | None) -> UrlCheckResult:
    """启动浏览器、单 URL 检测（适合无需复用上下文的场景）。"""
    path = screenshot_path
    with sync_playwright() as p:
        browser = launch_google_chrome_sync(p, cfg)
        try:
            context = _new_context(browser, cfg)
            page = context.new_page()
            try:
                return check_url_with_page(page, url, cfg, path)
            finally:
                context.close()
        finally:
            browser.close()


@contextmanager
def browser_session(cfg: AppConfig) -> Iterator[BrowserContext]:
    """同一出口 IP 下复用一个 BrowserContext（同步 API；runner 已改用异步分批入口）。"""
    with sync_playwright() as p:
        browser = launch_google_chrome_sync(p, cfg)
        context = _new_context(browser, cfg)
        try:
            yield context
        finally:
            context.close()
            browser.close()


def format_cell_status(result: UrlCheckResult) -> str:
    def _dedup_fields(*vals: str) -> list[str]:
        out: list[str] = []
        for v in vals:
            t = (v or "").strip()
            if not t:
                continue
            if any(t == x or t in x or x in t for x in out):
                continue
            out.append(t)
        return out

    if result.label == "success":
        fields = _dedup_fields("正常", result.summary, result.final_url or "")
        return " | ".join(fields)
    if result.label == "blocked":
        fields = _dedup_fields("受限/拒绝", result.summary, result.final_url or "")
        return " | ".join(fields)
    if result.label == "challenge":
        fields = _dedup_fields("验证墙", result.summary, result.final_url or "")
        return " | ".join(fields)
    if result.label == "skipped":
        fields = _dedup_fields("已跳过（未测浏览器）", result.summary, result.error_message or "")
        return " | ".join(fields)
    fields = _dedup_fields("失败", result.summary, result.error_message or "", result.final_url or "")
    return " | ".join(fields)
