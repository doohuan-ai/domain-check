"""
Chrome / Playwright 启动与 Context 选项（参考 aips-desktop 的 BrowserManager 思路）。

- 启动：`ignore_default_args` 去掉 `--enable-automation`，并追加常见反自动化特征参数（非 puppeteer stealth 全量移植）。
- 上下文：可选 locale / timezone，与 aips 中 zh-CN、Asia/Shanghai 一致时可配置。
- 注入：可选清理 Selenium/WebDriver 遗留 window 属性（不做 Canvas 噪声，避免干扰通用站点检测）。
"""

from __future__ import annotations

import platform
from typing import Any

from domain_test.config import AppConfig

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


def build_chromium_launch_kwargs(cfg: AppConfig) -> dict[str, Any]:
    """供 sync / async ``chromium.launch`` 共用的关键字参数（不含 channel / executable_path）。"""
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
