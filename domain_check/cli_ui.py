"""
终端 UI（Rich）：风格接近 Claude Code / 现代 CLI — 圆角分区、柔和配色、步骤与表格。
stdout 非 TTY（如管道、重定向）时自动降级为纯文本，无需额外参数。
"""

from __future__ import annotations

import argparse
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

from domain_check.browser_check import UrlCheckResult

T = TypeVar("T")

# 终端配色约定（尽量贴近常见 CLI 最佳实践）：
# - 大段正文/标题：不绑死 white/black，用 bold / dim，跟随终端默认前景（深浅色主题都可读）
# - 语义色（成功/警告/错误）：保留色相，用于短标签与边框，避免大段高饱和背景
# - 装饰色：accent / muted 用于分隔与次要信息
_THEME = {
    "dt.title": "bold",
    "dt.sub": "dim",
    "dt.step": "dim",
    "dt.ok": "spring_green1",
    "dt.warn": "dark_orange",
    "dt.err": "indian_red",
    "dt.accent": "bright_cyan",
    "dt.muted": "bright_black",
    "dt.table_head": "bold dim",
}

_THEME_OBJ = Theme(_THEME)


def themed_console(*, stderr: bool = False) -> Console:
    """与 RunUI 使用同一 Theme 的 Console（向导等未走 RunUI 的路径应使用本函数）。"""
    return Console(stderr=stderr, highlight=False, soft_wrap=True, theme=_THEME_OBJ)


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
    """一次 domain-check 运行的控制台输出封装。"""

    def __init__(self, *, plain: bool) -> None:
        self.plain = plain
        self.console = _make_console(plain=plain)

    def header(self, title: str, subtitle: str = "", panel_title: str = "") -> None:
        if self.plain:
            print(f"\n{'=' * 60}\n{title}")
            if subtitle:
                print(subtitle)
            print("=" * 60)
            return
        lines: list[Text | str] = [Text(title, style="dt.title")]
        if subtitle:
            lines.append(Text(""))
            lines.append(Text(subtitle, style="dt.sub"))
        self.console.print()
        self.console.print(
            Panel(
                Group(*lines),
                box=box.ROUNDED,
                border_style="dt.accent",
                title=Text(panel_title, style="dt.title") if panel_title else None,
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
            spinner_style="dt.accent",
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


def use_rich_stream(stream) -> bool:
    """某输出流是否适合 Rich（TTY）。"""
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _format_argparse_option_line(action: argparse.Action) -> str:
    parts: list[str] = []
    for flag in action.option_strings:
        if action.nargs == 0:
            parts.append(flag)
        else:
            meta = action.metavar or str(action.dest).upper()
            parts.append(f"{flag} {meta}")
    return ", ".join(parts)


def print_cli_help(parser: argparse.ArgumentParser, *, file=None) -> None:
    """``--help`` 与缺参提示：TTY 下用 Rich 表格；否则回退 argparse 文本。"""
    file = file or sys.stdout
    if not use_rich_stream(file):
        # 避免子类 ``print_help`` 与 ``print_cli_help`` 互相递归
        argparse.ArgumentParser.print_help(parser, file=file)
        return

    console = Console(file=file, theme=_THEME_OBJ, highlight=False, soft_wrap=True)
    usage_one_line = " ".join(parser.format_usage().strip().split())
    desc = (parser.description or "").strip()

    # 上框：首行显示程序名，标题显示描述
    body: list[Text | str] = [Text(parser.prog, style="dt.title"), Text(""), Text(usage_one_line, style="dt.sub")]

    console.print()
    console.print(
        Panel(
            Group(*body),
            title=Text(desc or parser.prog, style="dt.title"),
            border_style="dt.accent",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    # 参数表正文：不强制 #fff，沿用终端默认前景色（深浅色主题下都可读；见 README / 讨论）
    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="dt.muted",
        border_style="dt.muted",
        pad_edge=False,
    )
    table.add_column("选项", style="bold", no_wrap=True)
    table.add_column("说明")
    for action in parser._actions:
        if not action.option_strings:
            continue
        table.add_row(_format_argparse_option_line(action), action.help or "")
    console.print()
    console.print(
        Panel(table, title="[dt.muted]参数[/]", border_style="dt.muted", box=box.ROUNDED, padding=(0, 1))
    )
    console.print()


def print_cli_missing_command_hint(message: str, *, file=None) -> None:
    """未指定 --config / --template / --wizard 时的补充提示。"""
    file = file or sys.stderr
    if not use_rich_stream(file):
        print(f"\n{message}", file=file)
        return
    console = Console(file=file, theme=_THEME_OBJ, highlight=False, soft_wrap=True)
    console.print()
    console.print(
        Panel(
            Text(message, style="dt.warn"),
            title="[dt.table_head]提示[/]",
            border_style="dt.warn",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_cli_parse_error(parser: argparse.ArgumentParser, message: str, *, file=None) -> None:
    """argparse 校验失败时的统一输出。"""
    file = file or sys.stderr
    usage_one_line = " ".join(parser.format_usage().strip().split())
    if not use_rich_stream(file):
        print(usage_one_line, file=file)
        print(f"{parser.prog}: error: {message}", file=file)
        return
    Console(file=file, theme=_THEME_OBJ, highlight=False, soft_wrap=True).print(
        Panel(
            Group(Text(usage_one_line, style="dt.muted"), Text(message, style="dt.err")),
            title="[dt.title]参数错误[/]",
            border_style="dt.err",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def print_simple_runtime_error(message: str, *, file=None, title: str = "错误") -> None:
    """运行前错误（如配置文件不存在），与 RunUI.error 风格一致。"""
    file = file or sys.stderr
    if not use_rich_stream(file):
        print(message, file=file)
        return
    Console(file=file, theme=_THEME_OBJ, highlight=False, soft_wrap=True).print(
        Panel(
            Text(message, style="dt.err"),
            title=f"[dt.title]{title}[/]",
            border_style="dt.err",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
