from __future__ import annotations

from importlib import resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 纯文本返回公网 IP 的默认校验 URL（与 Cloudflare trace 等互补，降低单点误判）
DEFAULT_EGRESS_VERIFY_URLS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
)


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
    return resources.files("domain_check").joinpath("builtin_config.yaml").read_text(encoding="utf-8")


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
class RunConfig:
    """路由器 / NAT 失败时与浏览器巡检的解耦策略。"""

    # abort：任一出错 IP 上 SSH/NAT 失败则终止整轮；skip_ip：跳过该出口，Excel 写占位行（浏览器未跑）
    nat_failure_policy: str = "skip_ip"


@dataclass
class LoggingConfig:
    """可观测性：JSON 行日志（与 Excel 同一运行目录）。"""

    json_events_log: bool = False
    json_events_filename: str = "events.jsonl"


@dataclass
class ProbeConfig:
    """
    ``enabled``：是否启用探针（总开关）；为 true 时至少一类 URL 列表非空。
    ``urls``：trace/连通类探针；写 ``[]`` 关闭。
    ``egress_verify_urls``：纯文本 IP-echo 类；写 ``[]`` 关闭。
    """
    enabled: bool = False
    urls: list[str] = field(default_factory=list)
    timeout_ms: int = 8000
    egress_verify_urls: list[str] = field(
        default_factory=lambda: list(DEFAULT_EGRESS_VERIFY_URLS)
    )


@dataclass
class PrecheckConfig:
    """URL 前置网络预检（DNS/TCP/PING），用于线路健康度信号。"""

    enabled: bool = False
    dns: bool = True
    tcp: bool = True
    ping: bool = False
    ping_count: int = 1
    timeout_ms: int = 1500
    tcp_port: int = 443


@dataclass
class BrowserConfig:
    """默认使用本机 Google Chrome（Playwright channel 或显式路径），无痕通过启动参数实现。"""
    channel: str = "chrome"
    chrome_path: str | None = None
    incognito: bool = True
    headless: bool = True
    goto_timeout_ms: int = 60_000
    wait_until: str = "domcontentloaded"
    screenshot_on_success: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str | None = None
    # 每批并行打开的标签数；0 表示一批内同时打开全部 URL（仅批次之间间隔）
    tabs_batch_size: int = 0
    # 相邻两批之间等待毫秒（上一批全部加载结束后，再开下一批）
    tabs_batch_delay_ms: int = 0
    # 网络类（goto 超时、连接重置等）最大尝试次数与退避
    navigation_network_max_attempts: int = 3
    navigation_network_retry_delay_ms: int = 3000
    navigation_network_retry_backoff: float = 1.0
    # 内容类（已拿到文档但 HTTP 非成功等需再次 goto）最大尝试次数与退避（验证墙/关键词命中不重试）
    navigation_content_max_attempts: int = 1
    navigation_content_retry_delay_ms: int = 2000
    # 与 tabs_batch_size=0 配合：单批最多并发页签上限（0 表示不额外限制；建议大 URL 列表时设为 8–32）
    max_concurrent_tabs: int = 0
    # 同一批内各 URL 启动导航的错开间隔（毫秒）；0 表示同时发起。tabs_batch_size 为 0 时仍生效，用于缓和打满目标站
    tab_stagger_ms: int = 150
    # 参考 aips-desktop：去掉默认 automation 开关并追加轻量反检测启动参数（不含 --disable-web-security）
    use_stealth_launch_args: bool = True
    # 禁用 Chrome 扩展，减少 ERR_BLOCKED_BY_CLIENT（广告拦截扩展等）
    disable_chrome_extensions: bool = True
    # 追加传给 Chrome 的命令行（每项一个字符串）
    extra_chrome_args: list[str] = field(default_factory=list)
    # 浏览器 locale，空表示不设置（沿用 Playwright 默认）
    locale: str = ""
    # IANA 时区，如 Asia/Shanghai；空表示不设置
    timezone_id: str = ""
    # 在每个页面注入前清理 WebDriver/Selenium 遗留 window 属性（与 aips setupAntiDetectionScripts 同源思路，无 Canvas 篡改）
    inject_automation_cleanup_script: bool = True
    # goto 返回后是否尽量再等 load 事件（对 wait_until=domcontentloaded 的 SPA 有帮助；超时不影响后续）
    post_goto_try_load_state: bool = True
    # 等待 load 的超时毫秒（仅当 post_goto_try_load_state 为 true）
    post_goto_load_state_timeout_ms: int = 30_000
    # 导航后再固定等待毫秒，给前端渲染/水合时间，再截正文与截图；0 表示不额外休眠
    post_goto_settle_ms: int = 1500
    # 以下：HTTP 2xx 且通过关键词检查后，可选「随机冲浪」操作（仅异步路径）
    random_surfer_enabled: bool = False
    random_surfer_budget_ms: int = 12_000
    random_surfer_max_clicks: int = 3
    random_surfer_scroll: bool = True
    random_surfer_scroll_passes: int = 3
    random_surfer_mouse_wiggle: bool = True
    # true 时在随机冲浪前先保存一张“落地页”截图，避免点击后跳转/空白覆盖原始画面
    random_surfer_screenshot_before_actions: bool = True


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
    # 正文命中则判为「验证墙」类（与封禁区分）；不绕过验证码，仅标记
    captcha_keywords: list[str] = field(
        default_factory=lambda: [
            "slide to verify",
            "please slide",
            "unusual traffic",
            "verify you are human",
            "captcha",
            "访问过于频繁",
            "人机验证",
            "安全验证",
            "请完成安全验证",
        ]
    )


@dataclass
class OutputConfig:
    """报告根目录由 YAML ``output.dir`` 提供（默认 ``.`` 即 cwd）。"""
    dir: str = "."
    excel_prefix: str = "domain_check"
    embed_screenshot_max_width: int = 300
    embed_screenshot_max_height: int = 180
    data_row_height: float = 24.0
    # 单次运行截图文件总字节上限（超过则跳过后续截图）；0 表示不限制
    max_total_screenshot_bytes: int = 100_000_000


@dataclass
class AppConfig:
    """待测地址来自 YAML 顶层 ``urls``（列表或换行分隔的字符串）。"""
    urls: list[str] = field(default_factory=list)
    router: RouterConfig = field(default_factory=RouterConfig)
    nat: NatConfig = field(default_factory=NatConfig)
    run: RunConfig = field(default_factory=RunConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    probe: ProbeConfig = field(default_factory=ProbeConfig)
    precheck: PrecheckConfig = field(default_factory=PrecheckConfig)


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


def _parse_extra_chrome_args(browser_dict: dict[str, Any]) -> list[str]:
    raw = browser_dict.get("extra_chrome_args")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _parse_locale(browser_dict: dict[str, Any]) -> str:
    raw = browser_dict.get("locale")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def _parse_timezone_id(browser_dict: dict[str, Any]) -> str:
    raw = browser_dict.get("timezone_id")
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def _parse_egress_verify_urls(raw: Any) -> list[str]:
    if raw is None:
        return list(DEFAULT_EGRESS_VERIFY_URLS)
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    return list(DEFAULT_EGRESS_VERIFY_URLS)


def _parse_probe_dict(raw: Any) -> ProbeConfig:
    if not isinstance(raw, dict):
        return ProbeConfig()
    urls_raw = raw.get("urls")
    urls: list[str] = []
    if isinstance(urls_raw, list):
        urls = [str(u).strip() for u in urls_raw if str(u).strip()]
    return ProbeConfig(
        enabled=bool(raw.get("enabled", False)),
        urls=urls,
        timeout_ms=max(500, int(raw.get("timeout_ms", 8000))),
        egress_verify_urls=_parse_egress_verify_urls(raw.get("egress_verify_urls")),
    )


def _parse_precheck_dict(raw: Any) -> PrecheckConfig:
    if not isinstance(raw, dict):
        return PrecheckConfig()
    return PrecheckConfig(
        enabled=bool(raw.get("enabled", False)),
        dns=bool(raw.get("dns", True)),
        tcp=bool(raw.get("tcp", True)),
        ping=bool(raw.get("ping", False)),
        ping_count=max(1, int(raw.get("ping_count", 1))),
        timeout_ms=max(200, int(raw.get("timeout_ms", 1500))),
        tcp_port=max(1, min(65535, int(raw.get("tcp_port", 443)))),
    )


def _dict_to_appconfig(d: dict[str, Any]) -> AppConfig:
    r = d.get("router") or {}
    n = d.get("nat") or {}
    run_d = d.get("run") or {}
    log_d = d.get("logging") or {}
    b = d.get("browser") or {}
    a = d.get("access") or {}
    o = d.get("output") or {}
    pr = d.get("probe") or {}
    pc = d.get("precheck") or {}
    ch_raw = b.get("channel", "chrome")
    if ch_raw is None or (isinstance(ch_raw, str) and ch_raw.strip() == ""):
        channel_val = "chrome"
    else:
        channel_val = str(ch_raw)
    out_dir = o.get("dir", ".")
    if not isinstance(out_dir, str) or not str(out_dir).strip():
        out_dir = "."
    net_max = max(1, int(b.get("navigation_network_max_attempts", 3)))
    net_delay = max(0, int(b.get("navigation_network_retry_delay_ms", 3000)))
    net_backoff = float(b.get("navigation_network_retry_backoff", 1.0))
    cont_max = max(1, int(b.get("navigation_content_max_attempts", 1)))
    cont_delay = max(0, int(b.get("navigation_content_retry_delay_ms", 2000)))
    max_ct = int(b.get("max_concurrent_tabs", 0))
    nat_policy = str(run_d.get("nat_failure_policy", "skip_ip")).strip().lower()
    log_fn = str(log_d.get("json_events_filename", "events.jsonl")).strip() or "events.jsonl"
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
        run=RunConfig(nat_failure_policy=nat_policy),
        logging=LoggingConfig(
            json_events_log=bool(log_d.get("json_events_log", False)),
            json_events_filename=log_fn,
        ),
        browser=BrowserConfig(
            channel=channel_val,
            chrome_path=_parse_chrome_path(b),
            incognito=bool(b.get("incognito", True)),
            headless=bool(b.get("headless", True)),
            goto_timeout_ms=int(b.get("goto_timeout_ms", 60_000)),
            wait_until=str(b.get("wait_until", "domcontentloaded")),
            screenshot_on_success=bool(b.get("screenshot_on_success", True)),
            viewport_width=int(b.get("viewport_width", 1280)),
            viewport_height=int(b.get("viewport_height", 720)),
            user_agent=_parse_user_agent(b),
            tabs_batch_size=int(b.get("tabs_batch_size", 0)),
            tabs_batch_delay_ms=int(b.get("tabs_batch_delay_ms", 0)),
            navigation_network_max_attempts=net_max,
            navigation_network_retry_delay_ms=net_delay,
            navigation_network_retry_backoff=net_backoff,
            navigation_content_max_attempts=cont_max,
            navigation_content_retry_delay_ms=cont_delay,
            max_concurrent_tabs=max(0, max_ct),
            tab_stagger_ms=max(0, int(b.get("tab_stagger_ms", 150))),
            use_stealth_launch_args=bool(b.get("use_stealth_launch_args", True)),
            disable_chrome_extensions=bool(b.get("disable_chrome_extensions", True)),
            extra_chrome_args=_parse_extra_chrome_args(b),
            locale=_parse_locale(b),
            timezone_id=_parse_timezone_id(b),
            inject_automation_cleanup_script=bool(b.get("inject_automation_cleanup_script", True)),
            post_goto_try_load_state=bool(b.get("post_goto_try_load_state", True)),
            post_goto_load_state_timeout_ms=max(0, int(b.get("post_goto_load_state_timeout_ms", 30_000))),
            post_goto_settle_ms=max(0, int(b.get("post_goto_settle_ms", 1500))),
            random_surfer_enabled=bool(b.get("random_surfer_enabled", False)),
            random_surfer_budget_ms=max(500, int(b.get("random_surfer_budget_ms", 12_000))),
            random_surfer_max_clicks=max(0, int(b.get("random_surfer_max_clicks", 3))),
            random_surfer_scroll=bool(b.get("random_surfer_scroll", True)),
            random_surfer_scroll_passes=max(1, int(b.get("random_surfer_scroll_passes", 3))),
            random_surfer_mouse_wiggle=bool(b.get("random_surfer_mouse_wiggle", True)),
            random_surfer_screenshot_before_actions=bool(
                b.get("random_surfer_screenshot_before_actions", True)
            ),
        ),
        access=AccessConfig(
            enable_body_keyword_check=bool(a.get("enable_body_keyword_check", False)),
            body_text_max_chars=int(a.get("body_text_max_chars", 20_000)),
            block_keywords=list(a.get("block_keywords") or AccessConfig().block_keywords),
            captcha_keywords=(
                list(a["captcha_keywords"])
                if isinstance(a.get("captcha_keywords"), list)
                else AccessConfig().captcha_keywords
            ),
        ),
        output=OutputConfig(
            dir=str(out_dir).strip(),
            excel_prefix=str(o.get("excel_prefix", "domain_check")),
            embed_screenshot_max_width=int(o.get("embed_screenshot_max_width", 300)),
            embed_screenshot_max_height=int(o.get("embed_screenshot_max_height", 180)),
            data_row_height=float(o.get("data_row_height", 24)),
            max_total_screenshot_bytes=max(0, int(o.get("max_total_screenshot_bytes", 100_000_000))),
        ),
        probe=_parse_probe_dict(pr),
        precheck=_parse_precheck_dict(pc),
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


_WAIT_UNTIL_ALLOWED = frozenset({"load", "domcontentloaded", "networkidle", "commit"})


def validate_config_schema(cfg: AppConfig) -> None:
    """启动前校验：白名单、范围、路径等；失败抛出 ``ValueError``（可读中文信息）。"""
    errs: list[str] = []
    wu = (cfg.browser.wait_until or "").strip().lower()
    if wu not in _WAIT_UNTIL_ALLOWED:
        errs.append(
            "browser.wait_until 必须是 "
            + ", ".join(sorted(_WAIT_UNTIL_ALLOWED))
            + f"；当前: {cfg.browser.wait_until!r}"
        )
    if not (1 <= cfg.router.port <= 65535):
        errs.append(f"router.port 须在 1–65535；当前: {cfg.router.port}")
    gt = cfg.browser.goto_timeout_ms
    if not (1_000 <= gt <= 600_000):
        errs.append(f"browser.goto_timeout_ms 建议在 1000–600000；当前: {gt}")
    vw, vh = cfg.browser.viewport_width, cfg.browser.viewport_height
    if not (16 <= vw <= 7680 and 16 <= vh <= 4320):
        errs.append(f"browser 视口宽高异常: {vw}×{vh}（建议 16–7680 × 16–4320）")
    tbs = cfg.browser.tabs_batch_size
    if not (0 <= tbs <= 500):
        errs.append(f"browser.tabs_batch_size 须在 0–500；当前: {tbs}")
    mct = cfg.browser.max_concurrent_tabs
    if not (0 <= mct <= 200):
        errs.append(f"browser.max_concurrent_tabs 须在 0–200；当前: {mct}")
    nn = cfg.browser.navigation_network_max_attempts
    nc = cfg.browser.navigation_content_max_attempts
    if not (1 <= nn <= 30):
        errs.append(f"browser.navigation_network_max_attempts 须在 1–30；当前: {nn}")
    if not (1 <= nc <= 20):
        errs.append(f"browser.navigation_content_max_attempts 须在 1–20；当前: {nc}")
    if cfg.browser.navigation_network_retry_delay_ms < 0 or cfg.browser.navigation_network_retry_delay_ms > 600_000:
        errs.append("browser.navigation_network_retry_delay_ms 须在 0–600000")
    if cfg.browser.navigation_content_retry_delay_ms < 0 or cfg.browser.navigation_content_retry_delay_ms > 600_000:
        errs.append("browser.navigation_content_retry_delay_ms 须在 0–600000")
    bo = cfg.browser.navigation_network_retry_backoff
    if not (1.0 <= bo <= 3.0):
        errs.append(f"browser.navigation_network_retry_backoff 须在 1.0–3.0；当前: {bo}")
    o = cfg.output
    if o.embed_screenshot_max_width < 1 or o.embed_screenshot_max_width > 4000:
        errs.append(f"output.embed_screenshot_max_width 异常: {o.embed_screenshot_max_width}")
    if o.embed_screenshot_max_height < 1 or o.embed_screenshot_max_height > 4000:
        errs.append(f"output.embed_screenshot_max_height 异常: {o.embed_screenshot_max_height}")
    if o.max_total_screenshot_bytes < 0:
        errs.append("output.max_total_screenshot_bytes 不能为负")
    ac = cfg.access.body_text_max_chars
    if not (100 <= ac <= 2_000_000):
        errs.append(f"access.body_text_max_chars 建议在 100–2000000；当前: {ac}")
    pol = (cfg.run.nat_failure_policy or "").strip().lower()
    if pol not in ("abort", "skip_ip"):
        errs.append("run.nat_failure_policy 必须是 abort 或 skip_ip")
    cp = cfg.browser.chrome_path
    if cp and str(cp).strip():
        pth = Path(str(cp).strip()).expanduser()
        if not pth.is_file():
            errs.append(f"browser.chrome_path 不是有效文件: {pth}")
    if cfg.probe.enabled and not cfg.probe.urls and not cfg.probe.egress_verify_urls:
        errs.append(
            "probe.enabled 为 true 时，probe.urls 与 probe.egress_verify_urls 须至少一项非空"
            "（关闭某一类探针请将该列表设为 []）"
        )
    if len(cfg.urls) > 500:
        errs.append(f"urls 数量过多（>500），当前 {len(cfg.urls)}，请分批运行")
    if cfg.probe.enabled and cfg.probe.urls and len(cfg.probe.urls) > 40:
        errs.append(f"probe.urls 过多（>40），当前 {len(cfg.probe.urls)}")
    if cfg.probe.enabled and len(cfg.probe.egress_verify_urls) > 12:
        errs.append(
            f"probe.egress_verify_urls 过多（>12），当前 {len(cfg.probe.egress_verify_urls)}"
        )
    if cfg.precheck.timeout_ms < 200 or cfg.precheck.timeout_ms > 30_000:
        errs.append(f"precheck.timeout_ms 须在 200–30000；当前: {cfg.precheck.timeout_ms}")
    if cfg.precheck.ping_count < 1 or cfg.precheck.ping_count > 5:
        errs.append(f"precheck.ping_count 须在 1–5；当前: {cfg.precheck.ping_count}")
    if cfg.precheck.tcp_port < 1 or cfg.precheck.tcp_port > 65535:
        errs.append(f"precheck.tcp_port 须在 1–65535；当前: {cfg.precheck.tcp_port}")
    if cfg.precheck.enabled and not (cfg.precheck.dns or cfg.precheck.tcp or cfg.precheck.ping):
        errs.append("precheck.enabled=true 时，dns/tcp/ping 至少开启一项")
    if errs:
        raise ValueError("配置校验未通过:\n- " + "\n- ".join(errs))


def validate_config(cfg: AppConfig, *, require_router: bool = True) -> None:
    """
    require_router=False 时仅校验 urls（及 output 等已由 YAML 合并），
    供本机仅测 Playwright + Excel（与命令行 ``--skip-router`` 搭配）使用。
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
