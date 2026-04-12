"""解析项目内唯一配置文件 config.yaml 的路径。"""

from __future__ import annotations

from pathlib import Path


def resolve_config_yaml() -> Path:
    """
    固定读取项目根目录下的 config.yaml（不再通过命令行 -c 指定）。

    查找顺序：
    1. 从当前工作目录逐级向上，直到找到包含 config.yaml 的目录；
    2. 若未找到，且本包以可编辑方式安装在源码树中，则使用 domain_test 上一级目录下的 config.yaml。
    """
    cwd = Path.cwd().resolve()
    for d in [cwd, *cwd.parents]:
        p = d / "config.yaml"
        if p.is_file():
            return p

    # pip install -e . 时 __file__ 指向源码树中的 domain_test/*.py
    anchor = Path(__file__).resolve().parent.parent
    p = anchor / "config.yaml"
    if p.is_file():
        return p

    raise FileNotFoundError(
        "未找到 config.yaml：请在项目根目录下执行 domain-test（使当前工作目录为包含 config.yaml 的目录），"
        "或在项目根目录运行 pip install -e . 后再试。"
    )
