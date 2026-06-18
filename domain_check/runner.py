"""编排：拉取出口 IP → 切 NAT → Playwright 检测 → 写 Excel。

Copyright (c) 2026 doohuan-ai (REEF Jones)
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import paramiko
from playwright.sync_api import Error as PlaywrightError
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.text import Text
import yaml

from domain_check import distribution_version
from domain_check.browser_check import (
    UrlCheckResult,
    results_when_nat_skipped,
    run_urls_with_async_browser_sync,
)
from domain_check.cli_ui import (
    RunUI,
    print_cli_help,
    print_cli_missing_command_hint,
    print_cli_parse_error,
    print_simple_runtime_error,
    themed_console,
    use_rich_for_stdout,
)
from domain_check.config import (
    AppConfig,
    load_config,
    read_builtin_config_yaml_text,
    resolve_output_dir,
    validate_config,
    validate_config_schema,
)
from domain_check.probe_net import ProbeSummary, run_probe_summary
from domain_check.reporting_excel import build_workbook, save_workbook
from domain_check.router_ssh import change_nat, get_lo_ips
from domain_check.run_support import ScreenshotBudgetAsync


def _safe_file_tag(text: str) -> str:
    return text.replace(".", "_").replace(":", "_").replace("/", "_")


def _prepare_run_directory(
    cfg: AppConfig,
    config_path: Path | None = None,
    on_note: Callable[[str], None] | None = None,
) -> tuple[Path, int]:
    out_root, note = resolve_output_dir(cfg, config_path)
    if note and on_note:
        on_note(note)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = int(time.time())
    prefix = (cfg.output.excel_prefix or "syt_dc").strip() or "syt_dc"
    # 与 Excel 文件名前缀一致，便于识别同一轮输出目录
    run_dir = out_root / f"{prefix}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, run_id


def _write_excel_report(
    cfg: AppConfig,
    run_dir: Path,
    run_id: int,
    rows: list[tuple[str, list[UrlCheckResult]]],
    urls: list[str],
    probe_by_pub_ip: dict[str, ProbeSummary],
) -> Path:
    wb = build_workbook(cfg, rows, urls, probe_by_pub_ip)
    prefix = (cfg.output.excel_prefix or "syt_dc").strip() or "syt_dc"
    xlsx_path = run_dir / f"{prefix}_{run_id}.xlsx"
    save_workbook(wb, xlsx_path)
    return xlsx_path


# --skip-router 模式：Excel 第一列占位（无公网出口轮换）
_SKIP_ROUTER_PUB_LABEL = "本机(无路由器)"


def _yaml_blank_lines_between_top_keys(yaml_body: str) -> str:
    """在顶层键（如 urls:/browser:/probe:）之间插入空行，便于人工阅读。"""
    top = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")
    lines = yaml_body.rstrip("\n").split("\n") if yaml_body else []
    out: list[str] = []
    first_top = True
    for line in lines:
        if top.match(line):
            if not first_top and out and out[-1] != "":
                out.append("")
            first_top = False
        out.append(line)
    return "\n".join(out) + "\n"


def _make_json_event_logger(path: Path | None) -> Callable[[dict[str, Any]], None] | None:
    if path is None:
        return None
    lock = threading.Lock()

    def emit(ev: dict[str, Any]) -> None:
        line = json.dumps({"ts": time.time(), **ev}, ensure_ascii=False) + "\n"
        with lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

    return emit


def _collect_urls_interactive(c: Console | None) -> list[str]:
    if c:
        c.print(Text("请输入待测 URL（每行一个，输入空行结束）：", style="dt.step"))
    else:
        print("请输入待测 URL（每行一个，输入空行结束）：")
    out: list[str] = []
    while True:
        if c:
            s = Prompt.ask("  URL", default="").strip()
        else:
            s = input("> ").strip()
        if not s:
            break
        out.append(s)
    return out


def _run_wizard() -> int:
    rich_on = use_rich_for_stdout()
    c = themed_console() if rich_on else None
    if c:
        c.print(
            Panel(
                Group(
                    Text("syt-dc", style="dt.title"),
                    Text(""),
                    Text("syt-dc 新手向导", style="dt.sub"),
                    Text("按步骤输入关键参数，自动生成可运行配置。", style="dt.sub"),
                ),
                border_style="dt.accent",
                box=box.ROUNDED,
                title=Text("深云通 RouterOS 多出口 IP 网站可达性巡检", style="dt.title"),
                padding=(0, 1),
            )
        )
    out_default = "config.wizard.yaml"
    if c:
        out_raw = Prompt.ask("输出配置文件路径", default=out_default).strip()
    else:
        out_raw = input(f"输出配置文件路径（默认 {out_default}）: ").strip() or out_default
    out_path = Path(out_raw).expanduser()
    if out_path.is_dir():
        out_path = out_path / out_default
        if c:
            c.print(
                Panel(
                    Text(f"检测到目录输入，已自动使用文件：{out_path}", style="dt.sub"),
                    border_style="dt.muted",
                    box=box.ROUNDED,
                )
            )
        else:
            print(f"检测到目录输入，已自动使用文件：{out_path}")

    if out_path.exists():
        overwrite = Confirm.ask(f"文件已存在，是否覆盖？\n{out_path}", default=False) if c else (
            input(f"文件已存在（{out_path}），覆盖吗？[y/N]: ").strip().lower() == "y"
        )
        if not overwrite:
            if c:
                c.print(
                    Panel(Text("已取消。", style="dt.sub"), border_style="dt.muted", box=box.ROUNDED)
                )
            else:
                print("已取消。")
            return 1

    local_only = Confirm.ask("是否仅本机浏览器模式（跳过路由器/NAT）？", default=False) if c else (
        input("是否仅本机浏览器模式？[y/N]: ").strip().lower() == "y"
    )
    urls = _collect_urls_interactive(c)
    if not urls:
        if c:
            c.print(
                Panel(Text("至少需要 1 个 URL。", style="dt.warn"), border_style="dt.warn", box=box.ROUNDED)
            )
        else:
            print("至少需要 1 个 URL。")
        return 1

    headless = Confirm.ask("浏览器是否无头运行（headless）？", default=True) if c else (
        input("浏览器是否无头运行？[Y/n]: ").strip().lower() not in ("n", "no")
    )
    batch = IntPrompt.ask(
        Text.assemble("每批并发标签数 ", ("[0 = all]", "prompt.choices")),
        default=8,
    ) if c else int(input("每批并发标签数 [0 = all]: ").strip() or "8")
    probe_on = Confirm.ask("是否开启探针（urllib：trace + IP echo 等）？", default=True) if c else (
        input("是否开启探针？[Y/n]: ").strip().lower() not in ("n", "no")
    )
    precheck_on = Confirm.ask("是否开启 URL 前置预检（DNS/TCP/PING）？", default=True) if c else (
        input("是否开启 URL 前置预检？[Y/n]: ").strip().lower() not in ("n", "no")
    )
    excel_prefix = Prompt.ask("Excel 文件名前缀", default="syt_dc") if c else (
        input("Excel 文件名前缀（默认 syt_dc）: ").strip() or "syt_dc"
    )

    cfg: dict[str, Any] = {
        "urls": urls,
        "browser": {
            "headless": bool(headless),
            # 0 与 builtin 一致：一批内并行全部 URL（仍受 max_concurrent_tabs 约束）
            "tabs_batch_size": max(0, min(500, int(batch))),
            "goto_timeout_ms": 60000,
            "navigation_network_max_attempts": 3,
            "navigation_content_max_attempts": 1,
            "screenshot_on_success": True,
        },
        "probe": {
            "enabled": bool(probe_on),
            "timeout_ms": 8000,
            "urls": ["https://www.cloudflare.com/cdn-cgi/trace"],
        },
        "precheck": {
            "enabled": bool(precheck_on),
            "dns": True,
            "tcp": True,
            "ping": False,
            "ping_count": 1,
            "timeout_ms": 1500,
            "tcp_port": 443,
        },
        "output": {
            "excel_prefix": excel_prefix.strip() or "syt_dc",
            "dir": ".",
        },
    }
    if not local_only:
        if c:
            c.print(
                Panel(
                    Text("继续输入路由器参数（完整 NAT 流程必填）", style="dt.sub"),
                    border_style="dt.muted",
                    box=box.ROUNDED,
                    padding=(0, 1),
                )
            )
        host = Prompt.ask("router.host（路由器地址）") if c else input("router.host: ").strip()
        user = Prompt.ask("router.user（SSH 用户名）") if c else input("router.user: ").strip()
        pwd = Prompt.ask("router.password（SSH 密码）", password=True) if c else getpass.getpass("router.password: ")
        target_src = Prompt.ask("nat.target_src（NAT 规则源地址）") if c else input("nat.target_src: ").strip()
        cfg["router"] = {"host": host.strip(), "user": user.strip(), "password": pwd, "port": 22}
        cfg["nat"] = {"target_src": target_src.strip()}

    yaml_body = yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    yaml_body = _yaml_blank_lines_between_top_keys(yaml_body)
    txt = (
        "# 由 syt-dc --wizard 自动生成\n"
        "# 完整键与注释：syt-dc --template\n\n"
        + yaml_body
    )
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(txt, encoding="utf-8")
    except OSError as e:
        msg = f"写入配置失败：{out_path}\n{type(e).__name__}: {e}"
        if c:
            c.print(Panel(Text(msg, style="dt.err"), border_style="dt.err", box=box.ROUNDED))
        else:
            print(msg)
        return 1

    if c:
        cmd = f'syt-dc --config "{out_path}"' + (" --skip-router" if local_only else "")
        c.print(
            Panel(
                Group(
                    Text("配置已生成", style="dt.ok"),
                    Text(str(out_path.resolve()), style="dt.sub"),
                    Text(""),
                    Text("下一步运行：", style="dt.accent"),
                    Text(cmd, style="dt.accent"),
                ),
                border_style="dt.ok",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    else:
        print(f"配置已生成: {out_path.resolve()}")
        cmd = f'syt-dc --config "{out_path}"' + (" --skip-router" if local_only else "")
        print(f"下一步运行: {cmd}")
    return 0


def run_skip_router_only(
    cfg: AppConfig,
    ui: RunUI,
    config_path: Path | None = None,
) -> Path:
    """不 SSH、不切 NAT：只对 urls 跑 Playwright，并写与正式流程相同结构的 Excel。"""
    validate_config_schema(cfg)
    validate_config(cfg, require_router=False)

    run_dir, run_id = _prepare_run_directory(cfg, config_path, on_note=ui.step)
    urls = cfg.urls
    pub_ip = _SKIP_ROUTER_PUB_LABEL

    log_path = (run_dir / cfg.logging.json_events_filename) if cfg.logging.json_events_log else None
    emit = _make_json_event_logger(log_path)
    budget = (
        ScreenshotBudgetAsync(cfg.output.max_total_screenshot_bytes)
        if cfg.output.max_total_screenshot_bytes > 0
        else None
    )

    ui.header(
        "syt-dc",
        "本机浏览器巡检 · 跳过路由器 / NAT",
        "深云通 RouterOS 多出口 IP 网站可达性巡检",
    )
    ui.step(f"运行目录 {run_dir.name} · 待测 URL {len(urls)} 个")
    if emit:
        ui.step(f"JSON 事件日志: {log_path}")

    shot_paths = [run_dir / f"ip_{_safe_file_tag(pub_ip)}_url{idx}.png" for idx in range(1, len(urls) + 1)]
    run_meta = {"run_id": run_id, "round_index": 1, "pub_ip": pub_ip, "mode": "skip_router"}
    if emit:
        emit({"phase": "browser_phase_start", **run_meta, "n_urls": len(urls)})
    results = ui.browser_phase(
        f"Chrome 并行检测 {len(urls)} 个地址",
        lambda: run_urls_with_async_browser_sync(
            cfg,
            urls,
            shot_paths,
            event_log=emit,
            screenshot_budget=budget,
            run_meta=run_meta,
        ),
    )
    if emit:
        emit({"phase": "browser_phase_end", **run_meta})
    ui.results_table(urls, results, pub_ip)

    rows = [(pub_ip, results)]
    probe_by: dict[str, ProbeSummary] = {}
    if cfg.probe.enabled:
        ui.step("探针（urllib）检测中…")
        probe_by[pub_ip] = run_probe_summary(cfg, None)
    _warn_screenshot_budget(cfg, budget, ui)
    ui.step("写入 Excel …")
    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls, probe_by)
    ui.done(xlsx_path)
    return xlsx_path


def run(cfg: AppConfig, ui: RunUI, config_path: Path | None = None) -> Path:
    validate_config_schema(cfg)
    validate_config(cfg)

    ip_list = get_lo_ips(cfg)
    if not ip_list:
        raise RuntimeError(
            f"未从接口 {cfg.router.lo_interface} 解析到任何可用 IP，请检查路由器输出与 ssh_encoding。"
        )

    run_dir, run_id = _prepare_run_directory(cfg, config_path, on_note=ui.step)
    rows: list[tuple[str, list[UrlCheckResult]]] = []
    urls = cfg.urls
    probe_by: dict[str, ProbeSummary] = {}

    log_path = (run_dir / cfg.logging.json_events_filename) if cfg.logging.json_events_log else None
    emit = _make_json_event_logger(log_path)
    budget = (
        ScreenshotBudgetAsync(cfg.output.max_total_screenshot_bytes)
        if cfg.output.max_total_screenshot_bytes > 0
        else None
    )

    ui.header(
        "syt-dc",
        f"多出口巡检 · {len(ip_list)} 个公网 IP × {len(urls)} 个 URL",
        "深云通 RouterOS 多出口 IP 网站可达性巡检",
    )
    ui.step(f"运行目录 {run_dir.name}")
    if emit:
        ui.step(f"JSON 事件日志: {log_path}")
    _maybe_warn_screenshot_budget_preflight(cfg, len(ip_list), len(urls), ui)

    for round_index, pub_ip in enumerate(ip_list, start=1):
        ui.rule(f"出口 {pub_ip} (#{round_index}/{len(ip_list)})")
        ui.step("SSH 切换 SNAT …")
        run_meta = {"run_id": run_id, "round_index": round_index, "pub_ip": pub_ip, "mode": "router"}
        if emit:
            emit({"phase": "nat_attempt_start", **run_meta})
        try:
            change_nat(cfg, pub_ip)
        except Exception as e:
            if emit:
                emit({"phase": "nat_attempt_failed", **run_meta, "error": str(e), "exc_type": type(e).__name__})
            if cfg.run.nat_failure_policy == "abort":
                raise
            ui.step_warn(f"本出口 NAT/SSH 失败，已跳过浏览器与探针（策略: skip_ip）。{type(e).__name__}: {e}")
            rows.append((pub_ip, results_when_nat_skipped(urls, e)))
            probe_by[pub_ip] = ProbeSummary("off", "NAT/SSH 失败，未执行 urllib 探针")
            continue
        if emit:
            emit({"phase": "nat_attempt_ok", **run_meta})

        if cfg.probe.enabled:
            ps = run_probe_summary(cfg, pub_ip)
            probe_by[pub_ip] = ps
            if emit:
                emit(
                    {
                        "phase": "probe_done",
                        **run_meta,
                        "probe_state": ps.state,
                        "probe_detail": ps.detail[:500],
                        "egress_verify": (ps.egress_verify or "")[:800],
                    }
                )

        shot_paths = [run_dir / f"ip_{_safe_file_tag(pub_ip)}_url{idx}.png" for idx in range(1, len(urls) + 1)]
        if emit:
            emit({"phase": "browser_phase_start", **run_meta, "n_urls": len(urls)})
        results = ui.browser_phase(
            f"Chrome 并行检测 {len(urls)} 个地址",
            lambda: run_urls_with_async_browser_sync(
                cfg,
                urls,
                shot_paths,
                event_log=emit,
                screenshot_budget=budget,
                run_meta=run_meta,
            ),
        )
        if emit:
            emit({"phase": "browser_phase_end", **run_meta})
        ui.results_table(urls, results, pub_ip)

        rows.append((pub_ip, results))

    _warn_screenshot_budget(cfg, budget, ui)
    ui.step("写入 Excel …")
    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls, probe_by)
    ui.done(xlsx_path)
    return xlsx_path


def _warn_screenshot_budget(cfg: AppConfig, budget: ScreenshotBudgetAsync | None, ui: RunUI) -> None:
    if budget is None or not budget.is_limited:
        return
    line = budget.summary_line()
    if line:
        ui.step(line)


def _maybe_warn_screenshot_budget_preflight(
    cfg: AppConfig,
    n_ips: int,
    n_urls: int,
    ui: RunUI,
) -> None:
    cap = cfg.output.max_total_screenshot_bytes
    if cap <= 0 or n_ips <= 0 or n_urls <= 0:
        return
    # 粗估每张 PNG ~350KB（1280×720 视口常见量级）
    est = n_ips * n_urls * 350_000
    if est <= cap:
        return
    mb_cap = cap / (1024 * 1024)
    mb_est = est / (1024 * 1024)
    ui.step(
        f"预计截图约 {n_ips}×{n_urls}={n_ips * n_urls} 张（粗估 {mb_est:.0f} MB），"
        f"超过 output.max_total_screenshot_bytes={mb_cap:.0f} MB；"
        f"后半段可能无截图。建议调大该值或设为 0（不限制）。"
    )


class _PrintLicenseAction(argparse.Action):
    """输出 SPDX / AGPL 说明（与 ``pyproject`` 的 license 字段一致）。"""

    def __init__(
        self,
        option_strings: list[str],
        dest: str = argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        nargs: int = 0,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("help", "显示许可证说明")
        super().__init__(option_strings, dest, nargs=nargs, default=default, **kwargs)

    def __call__(self, parser: argparse.ArgumentParser, namespace, values, option_string=None) -> None:
        lic = "AGPL-3.0-only"
        try:
            import importlib.metadata as imd

            meta = imd.metadata("syt-dc")
            lic = (meta.get("License", "") or lic).strip() or lic
        except Exception:
            pass
        lines = [
            f"{parser.prog} — SPDX / 许可证: {lic}",
            "完整法律文本见安装包内 LICENSE 或项目根目录 LICENSE，以及:",
            "https://www.gnu.org/licenses/agpl-3.0.html",
            "",
            "若组织政策不允许 AGPL 或需商业授权，请联系: reef@doohuan.com（见 README）。",
        ]
        sys.stdout.write("\n".join(lines) + "\n")
        parser.exit(0)


class _RichHelpAction(argparse.Action):
    """TTY 下由 ``print_cli_help`` 输出 Rich 版帮助。"""

    def __init__(
        self,
        option_strings: list[str],
        dest: str = argparse.SUPPRESS,
        default=argparse.SUPPRESS,
        nargs: int = 0,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("help", "显示帮助")
        super().__init__(option_strings, dest, nargs=nargs, default=default, **kwargs)

    def __call__(self, parser: argparse.ArgumentParser, namespace, values, option_string=None) -> None:
        print_cli_help(parser, file=sys.stdout)
        parser.exit(0)


class DomainCheckArgumentParser(argparse.ArgumentParser):
    def print_help(self, file=None) -> None:
        print_cli_help(self, file=file or sys.stdout)

    def error(self, message: str) -> None:
        print_cli_parse_error(self, message, file=sys.stderr)
        self.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = DomainCheckArgumentParser(
        prog="syt-dc",
        description="深云通 RouterOS 多出口 IP 网站可达性巡检",
        usage=(
            "%(prog)s [--help] [--version] [--license] | "
            "--wizard | --template | --config PATH [--skip-router]"
        ),
        add_help=False,
    )
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    parser.add_argument(
        "--help",
        action=_RichHelpAction,
        nargs=0,
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {distribution_version()} (Python {py})",
        help="显示版本号",
    )
    g = parser.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--wizard",
        action="store_true",
        help="交互式向导",
    )
    g.add_argument(
        "--template",
        action="store_true",
        help="输出默认配置模板",
    )
    g.add_argument(
        "--config",
        metavar="PATH",
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--skip-router",
        action="store_true",
        help="跳过路由器校验与 SSH/NAT",
    )
    parser.add_argument(
        "--license",
        action=_PrintLicenseAction,
        nargs=0,
        default=argparse.SUPPRESS,
        help="显示 SPDX 许可证标识与条文链接",
    )
    args = parser.parse_args(argv)

    if (args.template or args.wizard) and args.config is not None:
        parser.error("不能同时指定 --template/--wizard 与 --config")
    if (args.template or args.wizard) and args.skip_router:
        parser.error("--template/--wizard 不能与 --skip-router 同时使用")
    if not args.template and not args.wizard and args.config is None:
        print_cli_help(parser, file=sys.stderr)
        print_cli_missing_command_hint("必须指定 --wizard 或 --template 或 --config PATH")
        return 2

    if args.template:
        text = read_builtin_config_yaml_text()
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    if args.wizard:
        return _run_wizard()

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print_simple_runtime_error(f"配置文件不存在: {cfg_path.resolve()}")
        return 1

    rich_on = use_rich_for_stdout()
    ui = RunUI(plain=not rich_on)

    try:
        cfg = load_config(cfg_path)
        if args.skip_router:
            run_skip_router_only(cfg, ui, config_path=cfg_path)
        else:
            run(cfg, ui, config_path=cfg_path)
    except (
        ValueError,
        RuntimeError,
        OSError,
        FileNotFoundError,
        paramiko.SSHException,
        PlaywrightError,
    ) as e:
        ui.error(e)
        return 1
    return 0


def cli_entry() -> None:
    """setuptools console_scripts 入口。"""
    raise SystemExit(main())


if __name__ == "__main__":
    cli_entry()
