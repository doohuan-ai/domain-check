"""URL 前置网络预检：DNS/TCP/PING（轻量信号，不替代浏览器检测）。"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from domain_check.config import AppConfig


@dataclass(frozen=True)
class UrlPrecheckSummary:
    state: str
    line_health: str
    detail: str


def _host_port_from_url(url: str, fallback_port: int) -> tuple[str, int]:
    p = urlparse(url.strip())
    host = p.hostname or ""
    if not host:
        return "", fallback_port
    if p.port:
        return host, p.port
    if p.scheme == "http":
        return host, 80
    if p.scheme == "https":
        return host, 443
    return host, fallback_port


def run_url_precheck(url: str, cfg: AppConfig) -> UrlPrecheckSummary:
    pc = cfg.precheck
    if not pc.enabled:
        return UrlPrecheckSummary("off", "未检测", "关闭")

    host, port = _host_port_from_url(url, pc.tcp_port)
    if not host:
        return UrlPrecheckSummary("fail", "异常", "URL 解析失败（缺少 host）")

    timeout_s = max(0.2, pc.timeout_ms / 1000.0)
    parts: list[str] = []
    pass_n = 0
    fail_n = 0

    if pc.dns:
        t0 = time.perf_counter()
        try:
            _ = socket.getaddrinfo(host, None)
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"DNS✅ {ms}ms")
            pass_n += 1
        except OSError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"DNS❌ {ms}ms ({e})")
            fail_n += 1
    else:
        parts.append("DNS-")

    if pc.tcp:
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                pass
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"TCP:{port}✅ {ms}ms")
            pass_n += 1
        except OSError as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"TCP:{port}❌ {ms}ms ({e})")
            fail_n += 1
    else:
        parts.append("TCP-")

    if pc.ping:
        t0 = time.perf_counter()
        try:
            cmd = ["ping", "-c", str(pc.ping_count), host]
            sp = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=max(2.0, timeout_s * pc.ping_count + 1.0),
            )
            ms = int((time.perf_counter() - t0) * 1000)
            if sp.returncode == 0:
                parts.append(f"PING✅ {ms}ms")
                pass_n += 1
            else:
                parts.append(f"PING❌ {ms}ms")
                fail_n += 1
        except Exception as e:
            ms = int((time.perf_counter() - t0) * 1000)
            parts.append(f"PING❌ {ms}ms ({type(e).__name__})")
            fail_n += 1
    else:
        parts.append("PING-")

    if fail_n == 0 and pass_n > 0:
        return UrlPrecheckSummary("ok", "健康", " | ".join(parts))
    if pass_n > 0 and fail_n > 0:
        return UrlPrecheckSummary("partial", "一般", " | ".join(parts))
    return UrlPrecheckSummary("fail", "异常", " | ".join(parts))

