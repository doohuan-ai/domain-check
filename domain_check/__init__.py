"""深云通 RouterOS 多出口 IP 网站可达性巡检"""

from __future__ import annotations

import importlib.metadata

__version__ = "0.1.0"


def distribution_version() -> str:
    """已安装发行版用包元数据；开发目录直跑等场景回退到 ``__version__``。"""
    try:
        return importlib.metadata.version("domain-check")
    except importlib.metadata.PackageNotFoundError:
        return __version__
