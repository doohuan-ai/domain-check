from __future__ import annotations

from importlib import resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典；override 中的键覆盖 base。"""
    out: dict[str, Any] = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_builtin_config_dict() -> dict[str, Any]:
    """读取包内 builtin_config.yaml。"""
    text = read_builtin_config_yaml_text()
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("内置 builtin_config.yaml 格式错误")
    return data


def read_builtin_config_yaml_text() -> str:
    """内置 YAML 原文（供 ``--template`` 与 ``load_builtin_config_dict``）。"""
    return resources.files("domain_test").joinpath("builtin_config.yaml").read_text(encoding="utf-8")


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
    chrome_path: str | None = None
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
    """报告根目录由 YAML ``output.dir`` 提供（默认 ``.`` 即 cwd）。"""
    dir: str = "."
    excel_prefix: str = "domain_check"
    embed_screenshot_max_width: int = 300
    embed_screenshot_max_height: int = 180
    data_row_height: float = 150


@dataclass
class AppConfig:
    """待测地址来自 YAML 顶层 ``urls``（列表或换行分隔的字符串）。"""
    urls: list[str] = field(default_factory=list)
    router: RouterConfig = field(default_factory=RouterConfig)
    nat: NatConfig = field(default_factory=NatConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _parse_urls(raw: Any) -> list[str]:
    if isinstance(raw, list):
        out: list[str] = []
        for u in raw:
            if isinstance(u, str) and u.strip():
                out.append(u.strip())
        return out
    if isinstance(raw, str):
        lines: list[str] = []
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            lines.append(s)
        return lines
    return []


def _parse_chrome_path(browser_dict: dict[str, Any]) -> str | None:
    raw = browser_dict.get("chrome_path")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _parse_user_agent(browser_dict: dict[str, Any]) -> str | None:
    ua = browser_dict.get("user_agent")
    if isinstance(ua, str) and ua.strip():
        return ua.strip()
    return None


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
    out_dir = o.get("dir", ".")
    if not isinstance(out_dir, str) or not str(out_dir).strip():
        out_dir = "."
    return AppConfig(
        urls=_parse_urls(d.get("urls")),
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
            chrome_path=_parse_chrome_path(b),
            incognito=bool(b.get("incognito", True)),
            headless=bool(b.get("headless", True)),
            goto_timeout_ms=int(b.get("goto_timeout_ms", 60_000)),
            wait_until=str(b.get("wait_until", "domcontentloaded")),
            screenshot_on_success=bool(b.get("screenshot_on_success", False)),
            viewport_width=int(b.get("viewport_width", 1280)),
            viewport_height=int(b.get("viewport_height", 720)),
            user_agent=_parse_user_agent(b),
        ),
        access=AccessConfig(
            enable_body_keyword_check=bool(a.get("enable_body_keyword_check", False)),
            body_text_max_chars=int(a.get("body_text_max_chars", 20_000)),
            block_keywords=list(a.get("block_keywords") or AccessConfig().block_keywords),
        ),
        output=OutputConfig(
            dir=str(out_dir).strip(),
            excel_prefix=str(o.get("excel_prefix", "domain_check")),
            embed_screenshot_max_width=int(o.get("embed_screenshot_max_width", 300)),
            embed_screenshot_max_height=int(o.get("embed_screenshot_max_height", 180)),
            data_row_height=float(o.get("data_row_height", 150)),
        ),
    )


def load_config(path: Path | str | None = None) -> AppConfig:
    """
    先加载包内 ``builtin_config.yaml``，若提供 ``path`` 则与其 YAML **深度合并**（文件覆盖同名字段）。
    全部运行参数均来自合并后的 YAML。
    """
    raw = load_builtin_config_dict()
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"配置文件不存在: {p.resolve()}")
        override = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(override, dict):
            raise ValueError(f"配置文件必须是 YAML 映射: {p}")
        raw = _deep_merge(raw, override)

    return _dict_to_appconfig(raw)


def resolve_output_dir(cfg: AppConfig) -> Path:
    d = cfg.output.dir.strip()
    path = Path(d).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def validate_config(cfg: AppConfig, *, require_router: bool = True) -> None:
    """
    require_router=False 时仅校验 urls（及 output 等已由 YAML 合并），
    供本机仅测 Playwright + Excel（--local-browser）使用。
    """
    missing = []
    if require_router:
        r = cfg.router
        if not r.host:
            missing.append("router.host（须在 --config 中填写）")
        if not r.user:
            missing.append("router.user")
        if not r.password:
            missing.append("router.password")
        if not cfg.nat.target_src:
            missing.append("nat.target_src")
    if not cfg.urls:
        missing.append("urls（须在 --config 中至少填写一个待测 URL）")
    if missing:
        raise ValueError("配置不完整: " + ", ".join(missing))
