"""Playwright：打开 URL、基于 HTTP/DOM 判定可达性，可选截图。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from domain_test.chrome_resolve import find_chrome_executable
from domain_test.config import AppConfig


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


def _launch_browser(p, cfg: AppConfig):
    """使用本机 Google Chrome：优先 browser.chrome_path，否则 channel=chrome，再否则探测常见安装路径。"""
    bcfg = cfg.browser
    args: list[str] = []
    if bcfg.incognito:
        args.append("--incognito")

    common: dict = {
        "headless": bcfg.headless,
        "args": args,
    }

    if bcfg.chrome_path:
        exe = Path(bcfg.chrome_path).expanduser()
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
    if bcfg.channel:
        try:
            return p.chromium.launch(**common, channel=bcfg.channel)
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


def _new_context(browser, cfg: AppConfig):
    bcfg = cfg.browser
    ctx_kwargs: dict = {
        "viewport": {"width": bcfg.viewport_width, "height": bcfg.viewport_height},
    }
    if bcfg.user_agent:
        ctx_kwargs["user_agent"] = bcfg.user_agent
    return browser.new_context(**ctx_kwargs)


def _body_text_sample(page, max_chars: int) -> str:
    try:
        t = page.inner_text("body", timeout=5_000)
    except PlaywrightError:
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
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
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
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"导航失败: {err_msg}",
            status_code=None,
            final_url=None,
            error_message=err_msg,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    final_url = page.url
    if response is not None:
        status_code = response.status

    if status_code is None:
        summary = "无 HTTP 响应（可能是非文档导航）"
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
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
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
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
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
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
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                pass
        return UrlCheckResult(
            ok=False,
            label="error",
            summary=f"非成功状态: HTTP {status_code}",
            status_code=status_code,
            final_url=final_url,
            error_message=f"HTTP {status_code}",
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )

    if acfg.enable_body_keyword_check:
        sample = _body_text_sample(page, acfg.body_text_max_chars)
        hit = _match_block_keywords(sample, acfg.block_keywords)
        if hit:
            if screenshot_path:
                try:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                except PlaywrightError:
                    pass
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
            page.screenshot(path=str(screenshot_path), full_page=True)
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
    """同一出口 IP 下复用一个 BrowserContext，每个 URL 使用独立 Page。"""
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
    return f"失败 | {result.summary} | {result.error_message or ''} | {result.final_url or ''}"
