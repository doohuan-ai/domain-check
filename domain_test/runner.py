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


_EPILOG = """
可在 -c 的 YAML 中传递的顶层键：
  urls              待测地址（字符串列表，或一段多行文本）
  router            SSH：host port user password lo_interface ssh_encoding nat_settle_seconds
  nat               target_src（SNAT 内网源 IP）
  browser           channel chrome_path incognito headless goto_timeout_ms wait_until
                    screenshot_on_success viewport_width viewport_height user_agent
  access            enable_body_keyword_check body_text_max_chars block_keywords
  output            dir excel_prefix embed_screenshot_* data_row_height

完整 YAML 模板（含全部 # 注释，与 builtin_config.yaml 一致）请运行：
  domain-test --print-template
""".strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="多出口 IP 网站可达性巡检（Playwright + RouterOS）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "-c",
        "--config",
        metavar="PATH",
        help="YAML 配置路径；与内置 builtin_config.yaml 深度合并",
    )
    g.add_argument(
        "--print-template",
        action="store_true",
        help="将内置完整 YAML 模板打印到 stdout 后退出（不写 -c）",
    )
    args = parser.parse_args(argv)

    if args.print_template:
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
