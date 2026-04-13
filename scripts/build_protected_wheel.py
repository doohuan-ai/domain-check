#!/usr/bin/env python3
"""
在临时目录中用 PyArmor 混淆 domain_check 后打 wheel，命令行入口仍为 domain-check。

说明：
- 混淆产物含 PyArmor 原生扩展（.so / .pyd），wheel 会带当前构建机的平台标签，并非 py3-none-any。
- 需在「要分发的目标操作系统 / 架构」上执行本脚本，或为各平台分别构建。
- PyArmor 试用版会在脚本中留下标记；正式对外分发请自行购买/配置 PyArmor 许可证。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "build" / "protected_staging"
PKG_SRC = ROOT / "domain_check"


def _write_staging_pyproject(dest: Path, base_pyproject: str, runtime_globs: list[str]) -> None:
    data_lines = ["[tool.setuptools.package-data]", "domain_check = ["]
    data_lines.append('    "builtin_config.yaml",')
    for g in runtime_globs:
        data_lines.append(f'    "{g}",')
    data_lines.append("]")
    block = "\n".join(data_lines) + "\n"
    if "[tool.setuptools.package-data]" in base_pyproject:
        base_pyproject = re.sub(
            r"\[tool\.setuptools\.package-data\][^\[]*",
            block,
            base_pyproject,
            count=1,
            flags=re.DOTALL,
        )
    else:
        base_pyproject = base_pyproject.rstrip() + "\n\n" + block
    dest.write_text(base_pyproject, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 PyArmor 混淆版 wheel")
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=ROOT / "dist" / "protected",
        help="wheel 输出目录（默认：dist/protected，避免覆盖源码构建的 wheel）",
    )
    args = parser.parse_args()

    if shutil.which("pyarmor") is None:
        print("未找到 pyarmor，请先安装：pip install '.[protected-build]'", file=sys.stderr)
        return 1

    shutil.rmtree(STAGING, ignore_errors=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    out_pkg = STAGING / "domain_check"

    cmd = [
        "pyarmor",
        "gen",
        "-r",
        "-i",
        "-O",
        str(out_pkg.parent),
        str(PKG_SRC),
    ]
    print("运行:", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

    shutil.copy2(PKG_SRC / "builtin_config.yaml", out_pkg / "builtin_config.yaml")

    runtimes = sorted(out_pkg.glob("pyarmor_runtime_*"))
    if not runtimes:
        print("混淆输出中未找到 pyarmor_runtime_*", file=sys.stderr)
        return 1
    runtime_globs: list[str] = []
    for _rt in runtimes:
        name = _rt.name
        runtime_globs.append(f"{name}/__init__.py")
        runtime_globs.extend(
            f"{name}/{p.name}" for p in _rt.iterdir() if p.suffix in (".so", ".pyd", ".dylib")
        )

    base_toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    _write_staging_pyproject(STAGING / "pyproject.toml", base_toml, runtime_globs)
    shutil.copy2(ROOT / "README.md", STAGING / "README.md")
    shutil.copy2(ROOT / "LICENSE", STAGING / "LICENSE")

    args.dist_dir.mkdir(parents=True, exist_ok=True)
    build_cmd = [
        sys.executable,
        "-m",
        "build",
        "--outdir",
        str(args.dist_dir.resolve()),
    ]
    print("运行:", " ".join(build_cmd), f"(cwd={STAGING})", flush=True)
    subprocess.run(build_cmd, cwd=STAGING, check=True)
    print("完成。请查看:", args.dist_dir.resolve(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
