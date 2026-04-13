"""编排：拉取出口 IP → 切 NAT → Playwright 检测 → 写 Excel。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import paramiko
from playwright.sync_api import Error as PlaywrightError

from domain_test.browser_check import UrlCheckResult, browser_session, check_url_with_page
from domain_test.config import AppConfig, load_config, read_builtin_config_yaml_text, resolve_output_dir, validate_config
from domain_test.reporting_excel import build_workbook
from domain_test.router_ssh import change_nat, get_lo_ips


def _safe_file_tag(text: str) -> str:
    return text.replace(".", "_").replace(":", "_").replace("/", "_")


def _prepare_run_directory(cfg: AppConfig) -> tuple[Path, int]:
    out_root = resolve_output_dir(cfg)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = int(time.time())
    run_dir = out_root / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, run_id


def _write_excel_report(cfg: AppConfig, run_dir: Path, run_id: int, rows: list[tuple[str, list[UrlCheckResult]]], urls: list[str]) -> Path:
    wb = build_workbook(cfg, rows, urls)
    xlsx_path = run_dir / f"{cfg.output.excel_prefix}_{run_id}.xlsx"
    wb.save(xlsx_path)
    return xlsx_path


# 仅测浏览器+Excel 时 Excel 第一列占位（无公网出口轮换）
_LOCAL_BROWSER_PUB_LABEL = "本机(无路由器)"


def run_local_browser_only(cfg: AppConfig) -> Path:
    """不 SSH、不切 NAT：只对 urls 跑 Playwright，并写与正式流程相同结构的 Excel。"""
    validate_config(cfg, require_router=False)

    run_dir, run_id = _prepare_run_directory(cfg)
    urls = cfg.urls
    results: list[UrlCheckResult] = []
    pub_ip = _LOCAL_BROWSER_PUB_LABEL

    print(f"\n===== 本机浏览器巡检（跳过路由器）=====")
    with browser_session(cfg) as context:
        for idx, url in enumerate(urls, start=1):
            print(f"  访问: {url}")
            fname = f"ip_{_safe_file_tag(pub_ip)}_url{idx}.png"
            shot_path = run_dir / fname

            page = context.new_page()
            try:
                res = check_url_with_page(page, url, cfg, shot_path)
            finally:
                page.close()

            print(f"  结果: {res.summary} ({res.label})")
            results.append(res)

    rows = [(pub_ip, results)]
    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls)
    print(f"\n完成（本机模式），报告: {xlsx_path}")
    return xlsx_path


def run(cfg: AppConfig) -> Path:
    validate_config(cfg)

    ip_list = get_lo_ips(cfg)
    if not ip_list:
        raise RuntimeError(
            f"未从接口 {cfg.router.lo_interface} 解析到任何可用 IP，请检查路由器输出与 ssh_encoding。"
        )

    run_dir, run_id = _prepare_run_directory(cfg)
    rows: list[tuple[str, list[UrlCheckResult]]] = []
    urls = cfg.urls

    for pub_ip in ip_list:
        print(f"\n===== 测试出口 IP: {pub_ip} =====")
        change_nat(cfg, pub_ip)

        results: list[UrlCheckResult] = []
        with browser_session(cfg) as context:
            for idx, url in enumerate(urls, start=1):
                print(f"  访问: {url}")
                fname = f"ip_{_safe_file_tag(pub_ip)}_url{idx}.png"
                shot_path = run_dir / fname

                page = context.new_page()
                try:
                    res = check_url_with_page(page, url, cfg, shot_path)
                finally:
                    page.close()

                print(f"  结果: {res.summary} ({res.label})")
                results.append(res)

        rows.append((pub_ip, results))

    xlsx_path = _write_excel_report(cfg, run_dir, run_id, rows, urls)
    print(f"\n完成，报告: {xlsx_path}")
    return xlsx_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="domain-test",
        description="多出口 IP 网站可达性巡检",
        usage="%(prog)s [--help] [--config PATH [--local-browser] | --template]",
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
        help="与 --config 合用：跳过路由器校验与 SSH/NAT，仅本机 Chrome 测 urls 并写 Excel",
    )
    g = parser.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--config",
        metavar="PATH",
        help="YAML 配置路径；与内置 builtin_config.yaml 深度合并",
    )
    g.add_argument(
        "--template",
        action="store_true",
        help="将内置完整 YAML 模板打印到 stdout 后退出（不写 --config）",
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

    try:
        cfg = load_config(cfg_path)
        if args.local_browser:
            run_local_browser_only(cfg)
        else:
            run(cfg)
    except (
        ValueError,
        RuntimeError,
        OSError,
        FileNotFoundError,
        paramiko.SSHException,
        PlaywrightError,
    ) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


def cli_entry() -> None:
    """setuptools console_scripts 入口。"""
    raise SystemExit(main())


if __name__ == "__main__":
    cli_entry()
