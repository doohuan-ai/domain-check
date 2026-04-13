"""编排：拉取出口 IP → 切 NAT → Playwright 检测 → 写 Excel。"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import paramiko
from playwright.sync_api import Error as PlaywrightError

from domain_test.browser_check import (
    UrlCheckResult,
    results_when_nat_skipped,
    run_urls_with_async_browser_sync,
)
from domain_test.cli_ui import RunUI, use_rich_for_stdout
from domain_test.config import (
    AppConfig,
    load_config,
    read_builtin_config_yaml_text,
    resolve_output_dir,
    validate_config,
    validate_config_schema,
)
from domain_test.probe_net import ProbeSummary, run_probe_summary
from domain_test.reporting_excel import build_workbook
from domain_test.router_ssh import change_nat, get_lo_ips
from domain_test.run_support import ScreenshotBudgetAsync


def _safe_file_tag(text: str) -> str:
    return text.replace(".", "_").replace(":", "_").replace("/", "_")


def _prepare_run_directory(cfg: AppConfig) -> tuple[Path, int]:
    out_root = resolve_output_dir(cfg)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = int(time.time())
    prefix = (cfg.output.excel_prefix or "domain_check").strip() or "domain_check"
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
    xlsx_path = run_dir / f"{cfg.output.excel_prefix}_{run_id}.xlsx"
    wb.save(xlsx_path)
    return xlsx_path


# 仅测浏览器+Excel 时 Excel 第一列占位（无公网出口轮换）
_LOCAL_BROWSER_PUB_LABEL = "本机(无路由器)"


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


def run_local_browser_only(cfg: AppConfig, ui: RunUI) -> Path:
    """不 SSH、不切 NAT：只对 urls 跑 Playwright，并写与正式流程相同结构的 Excel。"""
    validate_config_schema(cfg)
    validate_config(cfg, require_router=False)

    run_dir, run_id = _prepare_run_directory(cfg)
    urls = cfg.urls
    pub_ip = _LOCAL_BROWSER_PUB_LABEL

    log_path = (run_dir / cfg.logging.json_events_filename) if cfg.logging.json_events_log else None
    emit = _make_json_event_logger(log_path)
    budget = (
        ScreenshotBudgetAsync(cfg.output.max_total_screenshot_bytes)
        if cfg.output.max_total_screenshot_bytes > 0
        else None
    )

    ui.header("domain-test", "本机浏览器巡检 · 跳过路由器 / NAT")
    ui.step(f"运行目录 {run_dir.name} · 待测 URL {len(urls)} 个")
    if emit:
        ui.step(f"JSON 事件日志: {log_path}")

    shot_paths = [run_dir / f"ip_{_safe_file_tag(pub_ip)}_url{idx}.png" for idx in range(1, len(urls) + 1)]
    run_meta = {"run_id": run_id, "round_index": 1, "pub_ip": pub_ip, "mode": "local_browser"}
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
        probe_by[pub_ip] = run_probe_summary(cfg)
    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls, probe_by)
    ui.done(xlsx_path)
    return xlsx_path


def run(cfg: AppConfig, ui: RunUI) -> Path:
    validate_config_schema(cfg)
    validate_config(cfg)

    ip_list = get_lo_ips(cfg)
    if not ip_list:
        raise RuntimeError(
            f"未从接口 {cfg.router.lo_interface} 解析到任何可用 IP，请检查路由器输出与 ssh_encoding。"
        )

    run_dir, run_id = _prepare_run_directory(cfg)
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

    ui.header("domain-test", f"多出口巡检 · {len(ip_list)} 个公网 IP × {len(urls)} 个 URL")
    ui.step(f"运行目录 {run_dir.name}")
    if emit:
        ui.step(f"JSON 事件日志: {log_path}")

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
            ps = run_probe_summary(cfg)
            probe_by[pub_ip] = ps
            if emit:
                emit(
                    {
                        "phase": "probe_done",
                        **run_meta,
                        "probe_state": ps.state,
                        "probe_detail": ps.detail[:500],
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

    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls, probe_by)
    ui.done(xlsx_path)
    return xlsx_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="domain-test",
        description="多出口 IP 网站可达性巡检",
        usage="%(prog)s [--help] [--config PATH [--local-browser]] | --template",
        add_help=False,
    )
    parser.add_argument(
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="show this help message and exit",
    )
    parser.add_argument(
        "--local-browser",
        action="store_true",
        help="跳过路由器校验与 SSH/NAT，仅本机 Chrome 测 urls 并写 Excel（与 --config 合用）",
    )
    g = parser.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--config",
        metavar="PATH",
        help="YAML 配置路径",
    )
    g.add_argument(
        "--template",
        action="store_true",
        help="输出当前完整配置",
    )
    args = parser.parse_args(argv)

    if args.template and args.config is not None:
        parser.error("不能同时指定 --template 与 --config")
    if args.template and args.local_browser:
        parser.error("--template 不能与 --local-browser 同时使用")
    if not args.template and args.config is None:
        parser.print_help(sys.stderr)
        print("\n必须指定 --config PATH 或 --template", file=sys.stderr)
        return 2

    if args.template:
        text = read_builtin_config_yaml_text()
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        print(f"配置文件不存在: {cfg_path.resolve()}", file=sys.stderr)
        return 1

    rich_on = use_rich_for_stdout()
    ui = RunUI(plain=not rich_on)

    try:
        cfg = load_config(cfg_path)
        if args.local_browser:
            run_local_browser_only(cfg, ui)
        else:
            run(cfg, ui)
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
