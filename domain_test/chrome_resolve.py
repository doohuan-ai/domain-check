"""在本机查找 Google Chrome 可执行文件（Windows / macOS / Linux）。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def find_chrome_executable() -> Path | None:
    """
    在未指定 ``browser.chrome_path`` 时，按常见安装位置探测 Chrome：
    Windows：Program Files / ProgramFiles(x86) / LocalAppData；
    macOS：/Applications/Google Chrome.app/...；
    Linux：PATH 中的 google-chrome-stable、google-chrome、chrome。
    """
    if os.name == "nt":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pfx86) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        if local:
            candidates.append(Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe")
        for c in candidates:
            if c.is_file():
                return c
        return None

    if sys.platform == "darwin":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if p.is_file():
            return p
        return None

    for name in ("google-chrome-stable", "google-chrome", "chrome"):
        w = shutil.which(name)
        if w:
            return Path(w)
    return None
