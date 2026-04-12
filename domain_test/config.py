from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is not None and v != "":
        return v
    return default


def _env_int(name: str, default: int) -> int:
    v = _env(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


@dataclass
class RouterConfig:
    host: str = ""
    port: int = 22
    user: str = ""
    password: str = ""
    lo_interface: str = "lo"
    ssh_encoding: str = "utf-8"
    nat_settle_seconds: float = 8.0


@dataclass
class NatConfig:
    target_src: str = ""


@dataclass
class BrowserConfig:
    """默认使用本机 Google Chrome（Playwright channel 或显式路径），无痕通过启动参数实现。"""
    channel: str = "chrome"
    chrome_executable: str | None = None
    incognito: bool = True
    headless: bool = True
    goto_timeout_ms: int = 60_000
    wait_until: str = "domcontentloaded"
    screenshot_on_success: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str | None = None


@dataclass
class AccessConfig:
    enable_body_keyword_check: bool = False
    body_text_max_chars: int = 20_000
    block_keywords: list[str] = field(
        default_factory=lambda: [
            "access denied",
            "forbidden",
            "not available in your region",
            "not available in your country",
            "地区限制",
            "您所在的地区",
        ]
    )


@dataclass
class OutputConfig:
    """报告根目录仅由命令行 ``--output`` 注入，不从 YAML 读取。"""
    dir: str = ""
    excel_prefix: str = "domain_check"
    embed_screenshot_max_width: int = 300
    embed_screenshot_max_height: int = 180
    data_row_height: float = 150


@dataclass
class AppConfig:
    """urls 仅由命令行 --domains 注入，不从 YAML 读取。"""
    urls: list[str] = field(default_factory=list)
    router: RouterConfig = field(default_factory=RouterConfig)
    nat: NatConfig = field(default_factory=NatConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _dict_to_appconfig(d: dict[str, Any]) -> AppConfig:
    r = d.get("router") or {}
    n = d.get("nat") or {}
    b = d.get("browser") or {}
    a = d.get("access") or {}
    o = d.get("output") or {}
    ch_raw = b.get("channel", "chrome")
    if ch_raw is None or (isinstance(ch_raw, str) and ch_raw.strip() == ""):
        channel_val = "chrome"
    else:
        channel_val = str(ch_raw)
    cex = b.get("chrome_executable")
    chrome_exe: str | None = str(cex).strip() if isinstance(cex, str) and cex.strip() else None
    return AppConfig(
        urls=[],
        router=RouterConfig(
            host=str(r.get("host", "")),
            port=int(r.get("port", 22)),
            user=str(r.get("user", "")),
            password=str(r.get("password", "")),
            lo_interface=str(r.get("lo_interface", "lo")),
            ssh_encoding=str(r.get("ssh_encoding", "utf-8")),
            nat_settle_seconds=float(r.get("nat_settle_seconds", 8)),
        ),
        nat=NatConfig(target_src=str(n.get("target_src", ""))),
        browser=BrowserConfig(
            channel=channel_val,
            chrome_executable=chrome_exe,
            incognito=bool(b.get("incognito", True)),
            headless=bool(b.get("headless", True)),
            goto_timeout_ms=int(b.get("goto_timeout_ms", 60_000)),
            wait_until=str(b.get("wait_until", "domcontentloaded")),
            screenshot_on_success=bool(b.get("screenshot_on_success", False)),
            viewport_width=int(b.get("viewport_width", 1280)),
            viewport_height=int(b.get("viewport_height", 720)),
            user_agent=b.get("user_agent") if isinstance(b.get("user_agent"), str) else None,
        ),
        access=AccessConfig(
            enable_body_keyword_check=bool(a.get("enable_body_keyword_check", False)),
            body_text_max_chars=int(a.get("body_text_max_chars", 20_000)),
            block_keywords=list(a.get("block_keywords") or AccessConfig().block_keywords),
        ),
        output=OutputConfig(
            dir="",
            excel_prefix=str(o.get("excel_prefix", "domain_check")),
            embed_screenshot_max_width=int(o.get("embed_screenshot_max_width", 300)),
            embed_screenshot_max_height=int(o.get("embed_screenshot_max_height", 180)),
            data_row_height=float(o.get("data_row_height", 150)),
        ),
    )


def load_config(path: Path | str) -> AppConfig:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是 YAML 映射: {p}")
    cfg = _dict_to_appconfig(raw)

    r = cfg.router
    r.host = _env("ROUTER_HOST", r.host) or ""
    r.port = _env_int("ROUTER_PORT", r.port)
    r.user = _env("ROUTER_USER", r.user) or ""
    r.password = _env("ROUTER_PASSWORD", r.password) or ""

    if _env("DOMAIN_TEST_NAT_TARGET_SRC"):
        cfg.nat.target_src = _env("DOMAIN_TEST_NAT_TARGET_SRC", "") or ""

    chrome_env = _env("CHROME_PATH") or _env("GOOGLE_CHROME_BIN")
    if chrome_env:
        cfg.browser.chrome_executable = chrome_env

    return cfg


def resolve_output_dir(cfg: AppConfig) -> Path:
    d = cfg.output.dir.strip()
    path = Path(d).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def validate_config(cfg: AppConfig) -> None:
    missing = []
    r = cfg.router
    if not r.host:
        missing.append("ROUTER_HOST 或 config 中的 router.host")
    if not r.user:
        missing.append("ROUTER_USER 或 config 中的 router.user")
    if not r.password:
        missing.append("ROUTER_PASSWORD 或 config 中的 router.password")
    if not cfg.nat.target_src:
        missing.append("nat.target_src")
    if not cfg.urls:
        missing.append("命令行参数 --domains（域名列表文件）")
    if missing:
        raise ValueError("配置不完整: " + ", ".join(missing))
