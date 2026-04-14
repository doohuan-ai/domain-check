"""Excel 报告：纵向每 URL 一行、表头与状态列/截图列配色、探针列、截图 TwoCellAnchor 随单元格隐藏。"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.units import pixels_to_EMU
from domain_check.browser_check import UrlCheckResult, format_cell_status
from domain_check.config import AppConfig
from domain_check.probe_net import ProbeSummary

GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
SKIP_FILL = PatternFill("solid", fgColor="DEDEDE")
NEUTRAL_ROW = PatternFill("solid", fgColor="FFF7F7F7")

HEADER_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

_THIN = Side(style="thin", color="FFBFBFBF")
BORDER_THIN = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEADER_BOTTOM = Side(style="medium", color="FF2F5597")
BORDER_HEADER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_HEADER_BOTTOM)

DATA_ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
DATA_ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

_IMAGE_PAD_PX = 8


def _fill_for_result(result: UrlCheckResult) -> PatternFill:
    if result.label == "success":
        return GREEN
    if result.label in ("blocked", "challenge"):
        return YELLOW
    if result.label == "skipped":
        return SKIP_FILL
    return RED


def _probe_state_label(ps: ProbeSummary) -> str:
    m = {
        "off": "关闭",
        "empty": "无 URL",
        "ok": "正常",
        "partial": "部分失败",
        "fail": "失败",
    }
    return m.get(ps.state, ps.state)


def _probe_merged_cell(ps: ProbeSummary) -> str:
    """状态词 + 探针摘要，例如：正常 | www.cloudflare.com…→HTTP 200 · 981ms"""
    d = (ps.detail or "").strip()
    if ps.state == "off":
        return "—"
    if ps.state == "empty":
        return d or "—"
    word = _probe_state_label(ps)
    if not d:
        return word
    return f"{word} | {d}"


# 与 probe_net._abbrev 一致：U+2026 HORIZONTAL ELLIPSIS
_ELLIPSIS = "\u2026"


def _precheck_detail_for_excel(text: str) -> str:
    """预检详情：新版本已为多行 ``项 | 状态 | 耗时``；旧版单行 ``段 | 段`` 仍转为换行。"""
    t = (text or "").strip()
    if not t:
        return t
    if "\n" in t:
        return t
    # 旧格式（如 DNS✅ 1ms | TCP:443✅ 2ms），不含段内 ``项 | 状态 | 耗时`` 双竖线风格
    if " | " in t and " | 正常 | " not in t and " | 失败 | " not in t and " | — | " not in t:
        return t.replace(" | ", "\n")
    return t


def _probe_text_for_excel(ps: ProbeSummary) -> str:
    """探针列在省略号与箭头之间换行，例如 ``…→HTTP`` → ``…`` 换行后 ``→HTTP``。"""
    raw = _probe_merged_cell(ps)
    if _ELLIPSIS not in raw:
        return raw
    return raw.replace(f"{_ELLIPSIS}→", f"{_ELLIPSIS}\n→")


def _px_to_row_height_points(px: float) -> float:
    return px * 72.0 / 96.0


def _screenshot_display_size_px(cfg: AppConfig, target_h: int) -> tuple[int, int]:
    """视口比例下嵌入 Excel 的截图显示宽高（与浏览器视口一致时各图同尺寸）。"""
    vw = max(1, cfg.browser.viewport_width)
    vh = max(1, cfg.browser.viewport_height)
    tw = max(1, round(vw * target_h / vh))
    return tw, target_h


def _chars_for_screenshot_col(tw_px: int) -> float:
    """列宽（字符）≈ 容纳 tw_px + 左右留白。"""
    inner = tw_px + 2 * _IMAGE_PAD_PX + 4
    return min(92.0, max(18.0, inner / 7.0 + 2.5))


def build_workbook(
    cfg: AppConfig,
    rows: Sequence[tuple[str, list[UrlCheckResult]]],
    url_headers: list[str],
    probe_by_pub_ip: Mapping[str, ProbeSummary] | None = None,
) -> Workbook:
    """
    纵向表：每行一条 URL。
    probe_by_pub_ip: 公网 IP → 结构化探针结果（urllib 层，与浏览器列分离）；未启用时传 None。
    """
    wb = Workbook()
    ws = wb.active
    assert ws is not None

    ocfg = cfg.output
    target_h = int(ocfg.embed_screenshot_max_height)
    if target_h <= 0:
        target_h = 180

    tw_disp, th_disp = _screenshot_display_size_px(cfg, target_h)
    shot_col_wch = _chars_for_screenshot_col(tw_disp)

    headers = ["公网IP", "URL", "结果", "线路健康度", "预检详情(DNS/TCP/PING)", "探针", "截图"]
    ws.append(headers)

    # 列宽整体收窄，减少横向滚动成本，优先让用户先看到更多关键列
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 24
    ws.column_dimensions["D"].width = 15
    ws.column_dimensions["E"].width = 28
    ws.column_dimensions["F"].width = 20
    ws.column_dimensions["G"].width = shot_col_wch

    for col in range(1, 8):
        c = ws.cell(row=1, column=col)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = HEADER_ALIGN
        c.border = BORDER_HEADER

    last_row = 1
    probes = probe_by_pub_ip or {}

    for pub_ip, results in rows:
        ps = probes.get(pub_ip) or ProbeSummary("off", "")
        probe_text = _probe_text_for_excel(ps)
        for url, res in zip(url_headers, results):
            ws.append(
                [
                    pub_ip,
                    url,
                    format_cell_status(res),
                    res.line_health,
                    _precheck_detail_for_excel(res.precheck_detail),
                    probe_text,
                    "",
                ]
            )
            row_num = ws.max_row
            last_row = row_num
            # 整行使用与「结果」列一致的状态底色（正常/受限/验证墙/失败/跳过）
            status_fill = _fill_for_result(res)

            for col, al in (
                (1, DATA_ALIGN_LEFT),
                (2, DATA_ALIGN_LEFT),
                (3, DATA_ALIGN_LEFT),
                (4, DATA_ALIGN_CENTER),
                (5, DATA_ALIGN_LEFT),
                (6, DATA_ALIGN_LEFT),
                (7, DATA_ALIGN_CENTER),
            ):
                cell = ws.cell(row=row_num, column=col)
                cell.fill = status_fill
                cell.alignment = al
                cell.border = BORDER_THIN

            sp = res.screenshot_path
            if sp and Path(sp).is_file():
                p = Path(sp)
                try:
                    img = XLImage(str(p))
                    img.width = tw_disp
                    img.height = th_disp
                    h_px_total = th_disp + 2 * _IMAGE_PAD_PX
                    ws.row_dimensions[row_num].height = _px_to_row_height_points(h_px_total)
                    # twoCell：使用像素偏移定义非零锚区，避免零宽/零高导致 Excel 不显示图片
                    r0 = row_num - 1
                    img.anchor = TwoCellAnchor(
                        editAs="twoCell",
                        _from=AnchorMarker(
                            col=6,
                            colOff=pixels_to_EMU(_IMAGE_PAD_PX),
                            row=r0,
                            rowOff=pixels_to_EMU(_IMAGE_PAD_PX),
                        ),
                        to=AnchorMarker(
                            col=6,
                            colOff=pixels_to_EMU(_IMAGE_PAD_PX + tw_disp),
                            row=r0,
                            rowOff=pixels_to_EMU(_IMAGE_PAD_PX + th_disp),
                        ),
                    )
                    ws.add_image(img)
                except (OSError, ValueError, ImportError):
                    ws.row_dimensions[row_num].height = float(ocfg.data_row_height)
            else:
                ws.row_dimensions[row_num].height = float(ocfg.data_row_height)

    ws.freeze_panes = "A2"
    if last_row >= 1:
        ws.auto_filter.ref = f"A1:G{last_row}"

    return wb
