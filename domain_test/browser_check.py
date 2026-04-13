"""Playwright：打开 URL、基于 HTTP/DOM 判定可达性；视口截图；支持异步多标签分批与重试。"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from playwright.async_api import Error as AsyncPlaywrightError
from playwright.async_api import TimeoutError as AsyncPlaywrightTimeoutError
from playwright.async_api import async_playwright
from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from domain_test.browser_launch import (
    automation_cleanup_init_script,
    build_chromium_launch_kwargs,
    build_context_options,
)
from domain_test.chrome_resolve import find_chrome_executable
from domain_test.config import AppConfig
from domain_test.random_surfer import post_goto_random_surfer


@dataclass
class UrlCheckResult:
    ok: bool
    label: str
    summary: str
    status_code: int | None
    final_url: str | None
    error_message: str | None
    screenshot_path: str | None


_ALLOWED_WAIT = frozenset({"load", "domcontentloaded", "networkidle", "commit"})


def _normalize_wait_until(raw: str) -> str:
    w = (raw or "domcontentloaded").strip().lower()
    if w not in _ALLOWED_WAIT:
        return "domcontentloaded"
    return w


_CHROME_INSTALL_HINT = (
    "请先安装 Google Chrome（官方下载：https://www.google.com/chrome/ ）。\n"
    "若已安装但仍失败，请在 --config 指定的 YAML 里设置 browser.chrome_path 为可执行文件绝对路径。"
)


def _apply_context_init_scripts_sync(context, cfg: AppConfig) -> None:
    if cfg.browser.inject_automation_cleanup_script:
        context.add_init_script(automation_cleanup_init_script())


async def _apply_context_init_scripts_async(context, cfg: AppConfig) -> None:
    if cfg.browser.inject_automation_cleanup_script:
        await context.add_init_script(automation_cleanup_init_script())


def _launch_browser(p, cfg: AppConfig):
    """使用本机 Google Chrome：优先 browser.chrome_path，否则 channel=chrome，再否则探测常见安装路径。"""
    common = build_chromium_launch_kwargs(cfg)

    if cfg.browser.chrome_path:
        exe = Path(cfg.browser.chrome_path).expanduser()
        if not exe.is_file():
            raise FileNotFoundError(f"browser.chrome_path 不是有效文件: {exe}")
        try:
            return p.chromium.launch(**common, executable_path=str(exe))
        except PlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已指定 browser.chrome_path={exe}）。\n"
                f"{_CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    first_err: PlaywrightError | None = None
    ch = cfg.browser.channel
    if ch:
        try:
            return p.chromium.launch(**common, channel=ch)
        except PlaywrightError as e:
            first_err = e

    found = find_chrome_executable()
    if found is not None:
        try:
            return p.chromium.launch(**common, executable_path=str(found))
        except PlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已探测到可执行文件：{found}）。\n"
                f"{_CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    ex = RuntimeError(
        "未在本机检测到可用的 Google Chrome，且通过 Playwright channel 也无法启动。\n"
        f"{_CHROME_INSTALL_HINT}"
        + (f"\n首次尝试错误: {first_err}" if first_err else "")
    )
    if first_err is not None:
        raise ex from first_err
    raise ex


async def _launch_browser_async(p, cfg: AppConfig):
    common = build_chromium_launch_kwargs(cfg)

    if cfg.browser.chrome_path:
        exe = Path(cfg.browser.chrome_path).expanduser()
        if not exe.is_file():
            raise FileNotFoundError(f"browser.chrome_path 不是有效文件: {exe}")
        try:
            return await p.chromium.launch(**common, executable_path=str(exe))
        except AsyncPlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已指定 browser.chrome_path={exe}）。\n"
                f"{_CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    first_err: AsyncPlaywrightError | None = None
    ch = cfg.browser.channel
    if ch:
        try:
            return await p.chromium.launch(**common, channel=ch)
        except AsyncPlaywrightError as e:
            first_err = e

    found = find_chrome_executable()
    if found is not None:
        try:
            return await p.chromium.launch(**common, executable_path=str(found))
        except AsyncPlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已探测到可执行文件：{found}）。\n"
                f"{_CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    ex = RuntimeError(
        "未在本机检测到可用的 Google Chrome，且通过 Playwright channel 也无法启动。\n"
        f"{_CHROME_INSTALL_HINT}"
        + (f"\n首次尝试错误: {first_err}" if first_err else "")
    )
    if first_err is not None:
        raise ex from first_err
    raise ex


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


def _shot_sync(page, path: Path | None) -> None:
    if not path:
        return
    try:
        page.screenshot(path=str(path), full_page=False)
    except PlaywrightError:
        pass


async def _shot_async(page, path: Path | None) -> None:
    if not path:
        return
    try:
        await page.screenshot(path=str(path), full_page=False)
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
        err_msg = str(e) or "timeout"
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
        err_msg = str(e) or "playwright_error"
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
        cap_sample = _body_text_sample(page, acfg.body_text_max_chars)
        cap_hit = _match_block_keywords(cap_sample, acfg.captcha_keywords)
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


async def classify_after_goto_async(page, response, cfg: AppConfig, screenshot_path: Path | None) -> UrlCheckResult:
    """goto 已成功返回 response 后的分类（含重定向后的 final URL 与最终文档 HTTP 状态）。"""
    await _async_post_goto_settle(page, cfg)

    bcfg = cfg.browser
    acfg = cfg.access
    final_url = page.url
    status_code: int | None = response.status if response is not None else None

    if status_code is None:
        summary = "无 HTTP 响应（可能是非文档导航）"
        await _shot_async(page, screenshot_path)
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
        await _shot_async(page, screenshot_path)
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
        await _shot_async(page, screenshot_path)
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
        await _shot_async(page, screenshot_path)
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
        cap_sample = await _async_body_text_sample(page, acfg.body_text_max_chars)
        cap_hit = _match_block_keywords(cap_sample, acfg.captcha_keywords)
        if cap_hit:
            await _shot_async(page, screenshot_path)
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
            await _shot_async(page, screenshot_path)
            return UrlCheckResult(
                ok=False,
                label="blocked",
                summary=f"正文命中关键词: {hit}",
                status_code=status_code,
                final_url=final_url,
                error_message=None,
                screenshot_path=str(screenshot_path) if screenshot_path else None,
            )

    if bcfg.random_surfer_enabled:
        try:
            await post_goto_random_surfer(page, cfg)
        except AsyncPlaywrightError:
            pass

    shot: str | None = None
    if bcfg.screenshot_on_success and screenshot_path:
        try:
            await page.screenshot(path=str(screenshot_path), full_page=False)
            shot = str(screenshot_path)
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


async def _check_one_url_async(
    context,
    url: str,
    cfg: AppConfig,
    screenshot_path: Path | None,
    *,
    initial_delay_s: float = 0.0,
) -> UrlCheckResult:
    """单 URL：独立 Page，带导航重试（成功/受限即停止；错误类可重试至次数用尽）。"""
    if initial_delay_s > 0:
        await asyncio.sleep(initial_delay_s)

    bcfg = cfg.browser
    wait_until = _normalize_wait_until(bcfg.wait_until)
    timeout = bcfg.goto_timeout_ms
    max_att = bcfg.navigation_max_attempts
    retry_delay = bcfg.navigation_retry_delay_ms / 1000.0

    page = await context.new_page()
    last: UrlCheckResult | None = None
    try:
        for attempt in range(max_att):
            try:
                response = await page.goto(url, wait_until=wait_until, timeout=timeout)
            except AsyncPlaywrightTimeoutError as e:
                err_msg = str(e) or "timeout"
                await _shot_async(page, screenshot_path)
                last = UrlCheckResult(
                    ok=False,
                    label="error",
                    summary=f"超时: {err_msg}",
                    status_code=None,
                    final_url=page.url,
                    error_message=err_msg,
                    screenshot_path=str(screenshot_path) if screenshot_path else None,
                )
                if attempt < max_att - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return last
            except AsyncPlaywrightError as e:
                err_msg = str(e) or "playwright_error"
                await _shot_async(page, screenshot_path)
                last = UrlCheckResult(
                    ok=False,
                    label="error",
                    summary=f"导航失败: {err_msg}",
                    status_code=None,
                    final_url=None,
                    error_message=err_msg,
                    screenshot_path=str(screenshot_path) if screenshot_path else None,
                )
                if attempt < max_att - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return last

            last = await classify_after_goto_async(page, response, cfg, screenshot_path)
            if last.label in ("success", "blocked", "challenge"):
                return last
            if attempt < max_att - 1:
                await asyncio.sleep(retry_delay)
                continue
            return last
        return last if last is not None else UrlCheckResult(
            ok=False,
            label="error",
            summary="未知状态",
            status_code=None,
            final_url=None,
            error_message="未知状态",
            screenshot_path=None,
        )
    finally:
        await page.close()


def _batch_size_for(cfg: AppConfig, n_urls: int) -> int:
    bcfg = cfg.browser
    raw = bcfg.tabs_batch_size
    if raw <= 0:
        return n_urls if n_urls > 0 else 1
    return max(1, min(raw, n_urls)) if n_urls else 1


async def check_urls_in_batches_async(
    context,
    urls: list[str],
    cfg: AppConfig,
    screenshot_paths: list[Path | None],
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


async def run_urls_with_async_browser(cfg: AppConfig, urls: list[str], screenshot_paths: list[Path | None]) -> list[UrlCheckResult]:
    """启动一次浏览器 + 一个 Context，分批并行检测全部 URL。"""
    async with async_playwright() as p:
        browser = await _launch_browser_async(p, cfg)
        try:
            context = await _new_context_async(browser, cfg)
            try:
                return await check_urls_in_batches_async(context, urls, cfg, screenshot_paths)
            finally:
                await context.close()
        finally:
            await browser.close()


def run_urls_with_async_browser_sync(cfg: AppConfig, urls: list[str], screenshot_paths: list[Path | None]) -> list[UrlCheckResult]:
    """同步封装：内部 asyncio.run，供 runner 调用。"""
    return asyncio.run(run_urls_with_async_browser(cfg, urls, screenshot_paths))


def check_url(url: str, cfg: AppConfig, screenshot_path: Path | None) -> UrlCheckResult:
    """启动浏览器、单 URL 检测（适合无需复用上下文的场景）。"""
    path = screenshot_path
    with sync_playwright() as p:
        browser = _launch_browser(p, cfg)
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
        browser = _launch_browser(p, cfg)
        context = _new_context(browser, cfg)
        try:
            yield context
        finally:
            context.close()
            browser.close()


def format_cell_status(result: UrlCheckResult) -> str:
    if result.label == "success":
        return f"正常 | {result.summary} | {result.final_url or ''}"
    if result.label == "blocked":
        return f"受限/拒绝 | {result.summary} | {result.final_url or ''}"
    if result.label == "challenge":
        return f"验证墙 | {result.summary} | {result.final_url or ''}"
    return f"失败 | {result.summary} | {result.error_message or ''} | {result.final_url or ''}"
