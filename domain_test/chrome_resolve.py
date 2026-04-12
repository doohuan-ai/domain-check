"""在本机查找 Google Chrome 可执行文件（Windows / macOS / Linux）。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def find_chrome_executable() -> Path | None:
    """
    查找顺序：
    1. 环境变量 CHROME_PATH 或 GOOGLE_CHROME_BIN（若存在且为文件）
    2. Windows：Program Files / ProgramFiles(x86) / LocalAppData 下常见路径
    3. macOS：/Applications/Google Chrome.app/...
    4. Linux：PATH 中的 google-chrome-stable、google-chrome、chrome
    """
    for key in ("CHROME_PATH", "GOOGLE_CHROME_BIN"):
        env = os.environ.get(key)
        if env:
            p = Path(env).expanduser()
            if p.is_file():
                return p

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
