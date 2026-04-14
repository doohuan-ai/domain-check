"""可选 HTTP 探针：在本机当前路由/NAT 下用 urllib 快速探测 URL，与浏览器检测互补。"""

from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from domain_check.config import AppConfig


def _abbrev(url: str, max_len: int = 36) -> str:
    u = url.strip()
    if len(u) <= max_len:
        return u
    p = urlparse(u)
    host = (p.netloc or u)[:28]
    return f"{host}…"


@dataclass(frozen=True)
class ProbeSummary:
    """
    探针与浏览器 URL 分离：用 state 标记 urllib 层连通性，detail 为单行摘要。
    state: off（未启用）/ empty（无 URL）/ ok / partial / fail
    """

    state: str
    detail: str


def run_probe_summary(cfg: AppConfig) -> ProbeSummary:
    """
    对 ``cfg.probe.urls`` 依次 GET；返回结构化摘要（用于 Excel「探针（状态/摘要）」列）。
    """
    p = cfg.probe
    if not p.enabled:
        return ProbeSummary("off", "")
    if not p.urls:
        return ProbeSummary("empty", "（已启用但未配置 probe.urls）")

    timeout_s = max(0.5, p.timeout_ms / 1000.0)
    parts: list[str] = []
    ok_n = 0
    fail_n = 0
    for url in p.urls:
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
                _ = resp.read(16384)
            ms = int((time.perf_counter() - t0) * 1000)
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

    detail = " | ".join(parts)
    if fail_n == 0:
        state = "ok"
    elif ok_n == 0:
        state = "fail"
    else:
        state = "partial"
    return ProbeSummary(state, detail)
