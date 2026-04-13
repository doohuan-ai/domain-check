"""可选 HTTP 探针：在本机当前路由/NAT 下用 urllib 快速探测 URL，与浏览器检测互补。"""

from __future__ import annotations

import time
import urllib.request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from domain_test.config import AppConfig


def _abbrev(url: str, max_len: int = 36) -> str:
    u = url.strip()
    if len(u) <= max_len:
        return u
    p = urlparse(u)
    host = (p.netloc or u)[:28]
    return f"{host}…"


def run_probe_summary(cfg: AppConfig) -> str:
    """
    对 ``cfg.probe.urls`` 依次 GET，返回单行摘要（用于 Excel「出口探针」列）。
    未启用或列表为空时返回空串。
    """
    p = cfg.probe
    if not p.enabled or not p.urls:
        return ""
    timeout_s = max(0.5, p.timeout_ms / 1000.0)
    parts: list[str] = []
    for url in p.urls:
        u = url.strip()
        if not u:
            continue
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                u,
                headers={"User-Agent": "domain-test-probe/1"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                status = getattr(resp, "status", 200) or 200
                _ = resp.read(16384)
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→HTTP{status} {ms}ms")
        except HTTPError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→HTTP{e.code} {ms}ms")
        except URLError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→URLError {ms}ms ({e.reason!s})")
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"{_abbrev(u)}→{type(e).__name__} {ms}ms")
    return " | ".join(parts)
