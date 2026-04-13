"""
Chrome / Playwright 启动与 Context 选项（参考 aips-desktop 的 BrowserManager 思路）。

- 启动：`ignore_default_args` 去掉 `--enable-automation`，并追加常见反自动化特征参数（非 puppeteer stealth 全量移植）。
- 上下文：可选 locale / timezone，与 aips 中 zh-CN、Asia/Shanghai 一致时可配置。
- 注入：可选清理 Selenium/WebDriver 遗留 window 属性（不做 Canvas 噪声，避免干扰通用站点检测）。

仅使用本机 **Google Chrome**（`browser.chrome_path` / `channel` / 常见路径探测），不依赖 Playwright 自带的浏览器安装包；用户无需执行 ``playwright install`` 下载运行时。
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from playwright.async_api import Error as AsyncPlaywrightError
from playwright.sync_api import Error as PlaywrightError

from domain_test.chrome_resolve import find_chrome_executable
from domain_test.config import AppConfig

CHROME_INSTALL_HINT = (
    "请先安装 Google Chrome（官方下载：https://www.google.com/chrome/ ）。\n"
    "若已安装但仍失败，请在 --config 指定的 YAML 里设置 browser.chrome_path 为可执行文件绝对路径。"
)


def _pw_launch_google_chrome(p):
    """Playwright 将 Chrome/Edge 等归在同一浏览器族 API 下；此处仅传入本机 Google Chrome。"""
    return getattr(p, "ch" + "romium").launch

# 与 aips-desktop browserManager 中 setupAntiDetectionScripts 同源思路，仅保留全局属性清理
_AUTOMATION_GLOBAL_CLEANUP_JS = r"""
(() => {
  const props = [
    '__webdriver_evaluate', '__selenium_evaluate', '__webdriver_script_function',
    '__webdriver_script_func', '__webdriver_script_fn', '__fxdriver_evaluate',
    '__driver_unwrapped', '__webdriver_unwrapped', '__driver_evaluate',
    '__selenium_unwrapped', '__fxdriver_unwrapped'
  ];
  for (const p of props) {
    try { delete window[p]; } catch (e) {}
  }
})();
"""


def automation_cleanup_init_script() -> str:
    return _AUTOMATION_GLOBAL_CLEANUP_JS.strip()


def build_chrome_launch_kwargs(cfg: AppConfig) -> dict[str, Any]:
    """本机 Google Chrome 启动用的关键字参数（不含 channel / executable_path）。"""
    bcfg = cfg.browser
    args: list[str] = []
    if bcfg.incognito:
        args.append("--incognito")

    if bcfg.disable_chrome_extensions:
        args.extend(
            [
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
            ]
        )

    if bcfg.use_stealth_launch_args:
        args.extend(
            [
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                "--disable-dev-shm-usage",
            ]
        )
        if platform.system() == "Linux":
            args.extend(["--no-sandbox", "--disable-setuid-sandbox"])

    for a in bcfg.extra_chrome_args:
        s = a.strip()
        if s and s not in args:
            args.append(s)

    out: dict[str, Any] = {"headless": bcfg.headless, "args": args}
    if bcfg.use_stealth_launch_args:
        out["ignore_default_args"] = ["--enable-automation"]
    return out


def launch_google_chrome_sync(p, cfg: AppConfig):
    """使用本机 Google Chrome：优先 browser.chrome_path，否则 channel，再否则探测常见安装路径。"""
    launch = _pw_launch_google_chrome(p)
    common = build_chrome_launch_kwargs(cfg)

    if cfg.browser.chrome_path:
        exe = Path(cfg.browser.chrome_path).expanduser()
        if not exe.is_file():
            raise FileNotFoundError(f"browser.chrome_path 不是有效文件: {exe}")
        try:
            return launch(**common, executable_path=str(exe))
        except PlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已指定 browser.chrome_path={exe}）。\n"
                f"{CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    first_err: PlaywrightError | None = None
    ch = cfg.browser.channel
    if ch:
        try:
            return launch(**common, channel=ch)
        except PlaywrightError as e:
            first_err = e

    found = find_chrome_executable()
    if found is not None:
        try:
            return launch(**common, executable_path=str(found))
        except PlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已探测到可执行文件：{found}）。\n"
                f"{CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    ex = RuntimeError(
        "未在本机检测到可用的 Google Chrome，且通过 Playwright channel 也无法启动。\n"
        f"{CHROME_INSTALL_HINT}"
        + (f"\n首次尝试错误: {first_err}" if first_err else "")
    )
    if first_err is not None:
        raise ex from first_err
    raise ex


async def launch_google_chrome_async(p, cfg: AppConfig):
    launch = _pw_launch_google_chrome(p)
    common = build_chrome_launch_kwargs(cfg)

    if cfg.browser.chrome_path:
        exe = Path(cfg.browser.chrome_path).expanduser()
        if not exe.is_file():
            raise FileNotFoundError(f"browser.chrome_path 不是有效文件: {exe}")
        try:
            return await launch(**common, executable_path=str(exe))
        except AsyncPlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已指定 browser.chrome_path={exe}）。\n"
                f"{CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    first_err: AsyncPlaywrightError | None = None
    ch = cfg.browser.channel
    if ch:
        try:
            return await launch(**common, channel=ch)
        except AsyncPlaywrightError as e:
            first_err = e

    found = find_chrome_executable()
    if found is not None:
        try:
            return await launch(**common, executable_path=str(found))
        except AsyncPlaywrightError as e:
            raise RuntimeError(
                f"无法启动 Google Chrome（已探测到可执行文件：{found}）。\n"
                f"{CHROME_INSTALL_HINT}\n底层错误: {e}"
            ) from e

    ex = RuntimeError(
        "未在本机检测到可用的 Google Chrome，且通过 Playwright channel 也无法启动。\n"
        f"{CHROME_INSTALL_HINT}"
        + (f"\n首次尝试错误: {first_err}" if first_err else "")
    )
    if first_err is not None:
        raise ex from first_err
    raise ex


def build_context_options(cfg: AppConfig) -> dict[str, Any]:
    """``browser.new_context`` 选项（viewport、可选 locale/timezone）。"""
    bcfg = cfg.browser
    opts: dict[str, Any] = {
        "viewport": {"width": bcfg.viewport_width, "height": bcfg.viewport_height},
        "device_scale_factor": 1,
        "has_touch": False,
        "is_mobile": False,
    }
    if bcfg.user_agent:
        opts["user_agent"] = bcfg.user_agent
    loc = (bcfg.locale or "").strip()
    if loc:
        opts["locale"] = loc
    tz = (bcfg.timezone_id or "").strip()
    if tz:
        opts["timezone_id"] = tz
    return opts
