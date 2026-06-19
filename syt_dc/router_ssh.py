"""RouterOS SSH：拉取 loopback 出口 IP、切换 SNAT。

Copyright (c) 2026 doohuan-ai (REEF Jones)
"""

from __future__ import annotations

import re
import time

import paramiko

from syt_dc.config import AppConfig


def ssh_exec(cfg: AppConfig, cmd: str) -> str:
    r = cfg.router
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=r.host,
            port=r.port,
            username=r.user,
            password=r.password,
            timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )
        _stdin, stdout, _stderr = client.exec_command(cmd)
        data = stdout.read()
        return data.decode(r.ssh_encoding, errors="replace")
    finally:
        client.close()


def parse_lo_ips(output: str, interface: str) -> list[str]:
    """解析 `/ip address print detail where interface=...` 输出，跳过 disabled=yes 的条目。"""
    ips: list[str] = []
    if not output.strip():
        return ips

    blocks = re.split(r"\n(?=\s*\d+\s+)", output)
    iface_needle = f"interface={interface}"
    for block in blocks:
        if iface_needle not in block:
            continue
        m = re.search(r"address=([0-9a-fA-F:.]+)/", block)
        if not m:
            continue
        if re.search(r"\bdisabled=yes\b", block):
            continue
        ips.append(m.group(1))
    return ips


def get_lo_ips(cfg: AppConfig) -> list[str]:
    iface = cfg.router.lo_interface
    out = ssh_exec(cfg, f"/ip address print detail where interface={iface}")
    return parse_lo_ips(out, iface)


def change_nat(cfg: AppConfig, to_address: str) -> None:
    src = cfg.nat.target_src
    ssh_exec(
        cfg,
        f'/ip firewall nat set [find where src-address="{src}"] to-addresses={to_address}',
    )
    ssh_exec(cfg, "/ip firewall connection remove [find]")
    time.sleep(cfg.router.nat_settle_seconds)
