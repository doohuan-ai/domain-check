"""编排：拉取出口 IP → 切 NAT → Playwright 检测 → 写 Excel。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import paramiko
from playwright.sync_api import Error as PlaywrightError

from domain_test.browser_check import UrlCheckResult, browser_session, check_url_with_page
from domain_test.config import AppConfig, load_config, resolve_output_dir, validate_config
from domain_test.domains_file import load_domains_from_file
from domain_test.reporting_excel import build_workbook
from domain_test.router_ssh import change_nat, get_lo_ips


def _try_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _safe_file_tag(text: str) -> str:
    return text.replace(".", "_").replace(":", "_").replace("/", "_")


def apply_cli_args(cfg: AppConfig, args: argparse.Namespace) -> None:
    """将命令行参数写入内存中的 AppConfig（不写回磁盘）。"""
    out = getattr(args, "output", None)
    if out is not None and str(out).strip():
        cfg.output.dir = str(Path(out).expanduser())
    else:
        cfg.output.dir = "."

    if getattr(args, "headless", False) and getattr(args, "no_headless", False):
        raise ValueError("不能同时指定无头与有界面（如 -H 与 -W，或 --headless 与 --no-headless）")

    if getattr(args, "headless", False):
        cfg.browser.headless = True
    elif getattr(args, "no_headless", False):
        cfg.browser.headless = False

    to = getattr(args, "timeout", None)
    if to is not None:
        if to <= 0:
            raise ValueError("-t / --timeout 须为毫秒正整数")
        cfg.browser.goto_timeout_ms = int(to)


def run(cfg: AppConfig) -> Path:
    validate_config(cfg)

    ip_list = get_lo_ips(cfg)
    if not ip_list:
        raise RuntimeError(
            f"未从接口 {cfg.router.lo_interface} 解析到任何可用 IP，请检查路由器输出与 ssh_encoding。"
        )

    out_root = resolve_output_dir(cfg)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id = int(time.time())
    run_dir = out_root / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

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

    wb = build_workbook(cfg, rows, urls)
    xlsx_name = f"{cfg.output.excel_prefix}_{run_id}.xlsx"
    xlsx_path = run_dir / xlsx_name
    wb.save(xlsx_path)
    print(f"\n完成，报告: {xlsx_path}")
    return xlsx_path


def main(argv: list[str] | None = None) -> int:
    _try_load_dotenv()
    parser = argparse.ArgumentParser(description="多出口 IP 网站可达性巡检（Playwright + RouterOS）")
    parser.add_argument(
        "-d",
        "--domains",
        metavar="PATH",
        required=True,
        help="从文本文件读取待测 URL（每行一个，# 为注释）；短选项 -d",
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        default=None,
        help="可选：YAML 配置路径（-c）；与内置默认深度合并",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="DIR",
        default=None,
        help=(
            "报告根目录（可选，短选项 -o；未指定则使用当前工作目录）。"
            "相对路径相对 cwd；其下会创建 run_<时间戳>/。"
        ),
    )
    parser.add_argument(
        "-H",
        "--headless",
        action="store_true",
        help="强制无头模式（-H，覆盖 browser.headless）",
    )
    parser.add_argument(
        "-W",
        "--no-headless",
        action="store_true",
        help="有界面：弹出浏览器窗口（-W = Window；等同 --no-headless，便于调试）",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        metavar="MS",
        type=int,
        default=None,
        help="单次 page.goto 超时毫秒（-t，覆盖 browser.goto_timeout_ms）",
    )
    args = parser.parse_args(argv)

    cfg_path: Path | None = None
    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.is_file():
            print(f"配置文件不存在: {cfg_path.resolve()}", file=sys.stderr)
            return 1

    try:
        cfg = load_config(cfg_path)
        dom_path = Path(args.domains)
        if not dom_path.is_file():
            print(f"域名列表文件不存在: {dom_path.resolve()}", file=sys.stderr)
            return 1
        cfg.urls = load_domains_from_file(dom_path)
        apply_cli_args(cfg, args)
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
