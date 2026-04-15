"""可选 HTTP 探针：在本机当前路由/NAT 下用 urllib 快速探测 URL，与浏览器检测互补。"""

from __future__ import annotations

import ipaddress
import re
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from domain_check.config import AppConfig


def _abbrev(url: str, max_len: int = 36) -> str:
    u = url.strip()
    p = urlparse(u)
    host = (p.netloc or "").strip()
    if host:
        if len(host) > 28:
            host = host[:28] + "…"
        # 只要带路径，就显示 host + 省略号，避免某些 URL 显示全串、某些仅缩写不一致
        if (p.path and p.path != "/") or p.query:
            return f"{host}…"
        return host
    if len(u) <= max_len:
        return u
    return u[:28] + "…"


def _normalize_ip(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    try:
        return str(ipaddress.ip_address(t))
    except ValueError:
        return None


def _extract_ip_from_plain_body(body: str | bytes) -> str | None:
    """从纯文本响应中尽量解析首个合法 IPv4/IPv6。"""
    raw = body.decode("utf-8", errors="ignore") if isinstance(body, (bytes, bytearray)) else body
    t = raw.strip()
    if not t:
        return None
    for token in re.split(r"[\s,;<>\"']+", t):
        token = token.strip()
        if not token:
            continue
        n = _normalize_ip(token)
        if n:
            return n
    return None


def _plaintext_ip_get(url: str, timeout_s: float) -> tuple[str | None, str, int]:
    """
    GET 后解析响应体为 IP。
    返回 (ip 或 None, 人类可读摘要, 毫秒)。
    """
    u = url.strip()
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            u,
            headers={"User-Agent": "domain-check-probe/1"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", 200) or 200
            body = resp.read(4096)
        ms = int((time.perf_counter() - t0) * 1000)
        ip = _extract_ip_from_plain_body(body)
        ab = _abbrev(u)
        if ip:
            return ip, f"{ab}→{ip} · HTTP {status} · {ms}ms", ms
        return None, f"{ab}→无有效IP · HTTP {status} · {ms}ms", ms
    except HTTPError as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return None, f"{_abbrev(u)}→HTTP {e.code} · {ms}ms", ms
    except URLError:
        ms = int((time.perf_counter() - t0) * 1000)
        return None, f"{_abbrev(u)}→网络/解析失败 · {ms}ms", ms
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return None, f"{_abbrev(u)}→{type(e).__name__} · {ms}ms", ms


def _egress_verify_fetch_all(cfg: AppConfig) -> tuple[list[str], list[str | None]]:
    """请求所有 egress_verify_urls，返回 (摘要行列表, 解析到的规范化 IP 或 None)。"""
    urls = [u.strip() for u in cfg.probe.egress_verify_urls if u.strip()]
    if not urls:
        return [], []
    timeout_s = max(0.5, cfg.probe.timeout_ms / 1000.0)
    lines: list[str] = []
    ips: list[str | None] = []
    for u in urls:
        ip, line, _ms = _plaintext_ip_get(u, timeout_s)
        lines.append(line)
        ips.append(_normalize_ip(ip) if ip else None)
    return lines, ips


def _egress_verify_message(
    echo_lines: list[str],
    echo_ips: list[str | None],
    expected_egress_ip: str | None,
    cf_trace_ip: str | None,
) -> str:
    """第二套「看我 IP」结论文案 + 与路由器本批出口 / Cloudflare trace 交叉对照。"""
    if not echo_lines:
        return ""

    parts: list[str] = list(echo_lines)
    echo_ok = [ip for ip in echo_ips if ip]

    exp_norm = _normalize_ip(expected_egress_ip) if expected_egress_ip else None
    if exp_norm:
        parts.insert(0, f"路由器本批出口 {exp_norm}")

    cf_norm = _normalize_ip(cf_trace_ip) if cf_trace_ip else None
    if cf_norm:
        parts.append(f"Cloudflare trace ip {cf_norm}")

    uniq_echo = sorted(set(echo_ok))
    if len(uniq_echo) > 1:
        parts.append("外显不一致：各「看我IP」服务返回不同，可能有多层 NAT 或链路抖动")
    elif len(uniq_echo) == 1 and len(echo_ok) >= 2:
        parts.append("外显一致：多台外部探针返回相同公网 IP")

    if exp_norm:
        bad = [x for x in echo_ok if x != exp_norm]
        if echo_ok and not bad:
            parts.append("与路由器本批出口一致 ✓")
        elif echo_ok and bad:
            parts.append("与路由器本批出口不一致 ✗（请以探针外显为准排查 SNAT/策略路由）")
    elif echo_ok:
        parts.append("（无路由器期望 IP：本机/跳过路由模式，仅记录外显）")

    if cf_norm and uniq_echo:
        uq = uniq_echo[0]
        if uq != cf_norm:
            parts.append("提示：Cloudflare trace 与纯文本探针外显不同（常见于 CGNAT、企业代理或命中不同路径）")

    return " | ".join(parts)


def _egress_substate(echo_ips: list[str | None]) -> str:
    if not echo_ips:
        return "ok"
    ok_n = sum(1 for x in echo_ips if x)
    n = len(echo_ips)
    if ok_n == n:
        return "ok"
    if ok_n == 0:
        return "fail"
    return "partial"


def _combine_probe_states(a: str | None, b: str | None) -> str:
    """合并 trace 类探针子状态与「看我 IP」子状态；任一侧未启用时传 None。"""
    parts = [x for x in (a, b) if x is not None]
    if not parts:
        return "empty"
    if all(x == "ok" for x in parts):
        return "ok"
    if all(x == "fail" for x in parts):
        return "fail"
    return "partial"


@dataclass(frozen=True)
class ProbeSummary:
    """
    探针与浏览器 URL 分离：用 state 标记 urllib 层连通性，detail 为单行摘要。
    state: off（未启用）/ empty（无任务）/ ok / partial / fail
    """

    state: str
    detail: str
    profile: str = ""
    egress_verify: str = ""


def _trace_profile_from_kv(profile_kv: dict[str, str]) -> str:
    """探针链路画像：沿用 trace 英文键名（与 cdn-cgi/trace 一致），便于对照原始字段。"""
    order = ("ip", "loc", "colo", "visit_scheme", "http", "tls")
    profile_parts: list[str] = []
    for k in order:
        v = profile_kv.get(k)
        if v:
            profile_parts.append(f"{k} {v}")
    return " | ".join(profile_parts)


def run_probe_summary(cfg: AppConfig, expected_egress_ip: str | None = None) -> ProbeSummary:
    """
    ``probe.enabled`` 为总开关；``probe.urls`` 与 ``probe.egress_verify_urls`` 各自写 ``[]`` 关闭对应一类探针。
    摘要用于 Excel「探针」「探针链路画像」「出口校验」列。
    ``expected_egress_ip``：路由器本批次 loopback 公网 IP；供 egress 对照。
    """
    p = cfg.probe
    if not p.enabled:
        return ProbeSummary("off", "", "", "")

    trace_urls = [u.strip() for u in p.urls if u.strip()]
    egress_urls = [u.strip() for u in p.egress_verify_urls if u.strip()]
    if not trace_urls and not egress_urls:
        return ProbeSummary(
            "empty",
            "（probe.urls 与 probe.egress_verify_urls 均为空，无探针任务）",
            "",
            "",
        )

    timeout_s = max(0.5, p.timeout_ms / 1000.0)
    parts: list[str] = []
    profile_kv: dict[str, str] = {}
    ok_n = 0
    fail_n = 0
    url_state: str | None = None

    for url in trace_urls:
        u = url.strip()
        if not u:
            continue
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                u,
                headers={"User-Agent": "domain-check-probe/1"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                status = getattr(resp, "status", 200) or 200
                body = resp.read(16384)
            ms = int((time.perf_counter() - t0) * 1000)
            text = body.decode("utf-8", errors="ignore")
            for line in text.splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if k in {"ip", "loc", "colo", "visit_scheme", "http", "tls"} and v and k not in profile_kv:
                    profile_kv[k] = v
            parts.append(f"{_abbrev(u)}→HTTP {status} · {ms}ms")
            ok_n += 1
        except HTTPError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→HTTP {e.code} · {ms}ms")
            ok_n += 1
        except URLError:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→网络/解析失败 · {ms}ms")
            fail_n += 1
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→{type(e).__name__} · {ms}ms")
            fail_n += 1

    if trace_urls:
        if fail_n == 0:
            url_state = "ok"
        elif ok_n == 0:
            url_state = "fail"
        else:
            url_state = "partial"

    detail = " | ".join(parts) if parts else "（probe.urls=[]，未执行 trace/连通类探针）"
    profile = _trace_profile_from_kv(profile_kv) if trace_urls else ""

    echo_lines, echo_ips = _egress_verify_fetch_all(cfg)
    cf_for_egress = profile_kv.get("ip") if trace_urls else None
    egress = _egress_verify_message(echo_lines, echo_ips, expected_egress_ip, cf_for_egress)
    egress_state: str | None = _egress_substate(echo_ips) if egress_urls else None

    state = _combine_probe_states(url_state, egress_state)
    return ProbeSummary(state, detail, profile, egress)
