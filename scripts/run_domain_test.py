#!/usr/bin/env python3
"""CLI 入口：可从任意目录执行，脚本会把项目根加入 sys.path。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from domain_test.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
