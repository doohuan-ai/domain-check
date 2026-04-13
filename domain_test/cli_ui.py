"""
终端 UI（Rich）：风格接近 Claude Code / 现代 CLI — 圆角分区、柔和配色、步骤与表格。
stdout 非 TTY（如管道、重定向）时自动降级为纯文本，无需额外参数。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, TypeVar

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from domain_test.browser_check import UrlCheckResult

T = TypeVar("T")

# 偏暗色终端友好、对比度适中（与常见「代码助手」CLI 观感接近）
_THEME = {
    "dt.title": "bold white",
    "dt.sub": "dim",
    "dt.step": "dim cyan",
    "dt.ok": "spring_green1",
    "dt.warn": "dark_orange",
    "dt.err": "indian_red",
    "dt.accent": "bright_cyan",
    "dt.muted": "bright_black",
    "dt.table_head": "bold dim",
}

_THEME_OBJ = Theme(_THEME)


def _make_console(*, plain: bool, stderr: bool = False) -> Console:
    if plain:
        return Console(
            stderr=stderr,
            force_terminal=False,
            color_system=None,
            highlight=False,
            width=min(120, getattr(sys.stdout, "columns", 120) or 120),
        )
    return Console(stderr=stderr, highlight=False, soft_wrap=True, theme=_THEME_OBJ)


class RunUI:
    """一次 domain-test 运行的控制台输出封装。"""

    def __init__(self, *, plain: bool) -> None:
        self.plain = plain
        self.console = _make_console(plain=plain)

    def header(self, title: str, subtitle: str = "") -> None:
        if self.plain:
            print(f"\n{'=' * 60}\n{title}")
            if subtitle:
                print(subtitle)
            print("=" * 60)
            return
        lines: list[Text | str] = [Text(title, style="dt.title")]
        if subtitle:
            lines.append(Text(subtitle, style="dt.sub"))
        self.console.print()
        self.console.print(
            Panel(
                Group(*lines),
                box=box.ROUNDED,
                border_style="dt.muted",
                padding=(0, 1),
            )
        )

    def rule(self, label: str) -> None:
        if self.plain:
            print(f"\n--- {label} ---\n")
            return
        self.console.print(Rule(Text(label, style="dt.accent"), style="dt.muted"))

    def step(self, message: str) -> None:
        if self.plain:
            print(f"  {message}")
            return
        self.console.print(Text("› ", style="dt.muted") + Text(message, style="dt.step"))

    def step_warn(self, message: str) -> None:
        if self.plain:
            print(f"  [警告] {message}")
            return
        self.console.print(
            Text("! ", style="dt.warn") + Text(message, style="dt.warn"),
        )

    def browser_phase(self, message: str, fn: Callable[[], T]) -> T:
        if self.plain:
            print(f"  {message} …")
            return fn()
        with self.console.status(
            f"[dt.accent]{message}[/]",
            spinner="dots",
            spinner_style="cyan",
        ):
            return fn()

    def results_table(self, urls: list[str], results: list[UrlCheckResult], pub_label: str) -> None:
        if self.plain:
            print(f"\n  [{pub_label}]")
            for url, res in zip(urls, results):
                print(f"    {res.label:8}  {url}")
                print(f"             {res.summary}")
            return

        self.console.print()
        self.console.print(Text(f"结果 · {pub_label}", style="dt.table_head"))

        table = Table(
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="dt.table_head",
            border_style="dt.muted",
            pad_edge=False,
        )
        table.add_column("#", justify="right", style="dt.sub", width=3)
        table.add_column("状态", width=8)
        table.add_column("URL", ratio=2, overflow="ellipsis")
        table.add_column("摘要", ratio=1, overflow="ellipsis")

        for i, (url, res) in enumerate(zip(urls, results), start=1):
            st, style = _status_cell(res.label)
            table.add_row(
                str(i),
                Text(st, style=style),
                url,
                res.summary,
            )
        self.console.print(table)

    def done(self, xlsx_path: Path) -> None:
        if self.plain:
            print(f"\n完成 · 报告: {xlsx_path.resolve()}\n")
            return
        self.console.print()
        self.console.print(
            Panel(
                Text.assemble(
                    ("完成", "dt.ok"),
                    "\n",
                    (str(xlsx_path.resolve()), "dt.sub"),
                ),
                title="[dt.title]报告[/]",
                border_style="dt.ok",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
        self.console.print()

    def error(self, exc: BaseException) -> None:
        msg = f"{type(exc).__name__}: {exc}"
        if self.plain:
            print(msg, file=sys.stderr)
            return
        err_console = _make_console(plain=False, stderr=True)
        err_console.print(
            Panel(
                Text(msg, style="dt.err"),
                title="[dt.title]错误[/]",
                border_style="dt.err",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )


def _status_cell(label: str) -> tuple[str, str]:
    if label == "success":
        return "正常", "dt.ok"
    if label == "blocked":
        return "受限", "dt.warn"
    if label == "challenge":
        return "验证墙", "dt.warn"
    if label == "skipped":
        return "跳过", "dt.warn"
    return "失败", "dt.err"


def use_rich_for_stdout() -> bool:
    """是否启用 Rich：仅当 stdout 为 TTY 时开启；管道或非交互环境自动纯文本。"""
    return bool(sys.stdout.isatty())
