"""从文本文件读取待测 URL 列表。"""

from __future__ import annotations

from pathlib import Path


def load_domains_from_file(path: Path) -> list[str]:
    """
    每行一个 URL；首尾空白去除；空行与以 # 开头的行忽略。
    要求 URL 以 http:// 或 https:// 开头。
    """
    raw = path.read_text(encoding="utf-8")
    urls: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValueError(
                f"域名文件 {path} 第 {lineno} 行必须以 http:// 或 https:// 开头: {s!r}"
            )
        urls.append(s)
    if not urls:
        raise ValueError(f"域名列表文件为空或仅含注释: {path}")
    return urls
