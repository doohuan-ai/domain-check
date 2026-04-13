"""Excel 报告：纵向每 URL 一行、表头与状态列/截图列配色、探针列、截图 TwoCellAnchor 随单元格隐藏。"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from domain_test.browser_check import UrlCheckResult, format_cell_status
from domain_test.config import AppConfig
from domain_test.probe_net import ProbeSummary

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


def _line_health_fill(value: str) -> PatternFill:
    if value == "健康":
        return GREEN
    if value == "一般":
        return YELLOW
    if value == "异常":
        return RED
    return NEUTRAL_ROW


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

    headers = ["公网IP", "URL", "结果", "线路健康度", "预检详情(DNS/TCP/PING)", "探针状态", "出口探针详情", "截图"]
    ws.append(headers)

    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 46
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 40
    ws.column_dimensions["F"].width = 14
    ws.column_dimensions["G"].width = 36
    ws.column_dimensions["H"].width = shot_col_wch

    for col in range(1, 9):
        c = ws.cell(row=1, column=col)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = HEADER_ALIGN
        c.border = BORDER_HEADER

    last_row = 1
    probes = probe_by_pub_ip or {}

    for pub_ip, results in rows:
        ps = probes.get(pub_ip) or ProbeSummary("off", "")
        probe_state = _probe_state_label(ps)
        probe_detail = (ps.detail or "").strip() or "—"
        probe_state_fill = (
            GREEN
            if ps.state == "ok"
            else YELLOW
            if ps.state in ("partial", "fail", "empty")
            else NEUTRAL_ROW
        )
        for url, res in zip(url_headers, results):
            ws.append(
                [
                    pub_ip,
                    url,
                    format_cell_status(res),
                    res.line_health,
                    res.precheck_detail,
                    probe_state,
                    probe_detail,
                    "",
                ]
            )
            row_num = ws.max_row
            last_row = row_num
            status_fill = _fill_for_result(res)
            line_fill = _line_health_fill(res.line_health)

            for col, al, fill in (
                (1, DATA_ALIGN_LEFT, NEUTRAL_ROW),
                (2, DATA_ALIGN_LEFT, NEUTRAL_ROW),
                (3, DATA_ALIGN_LEFT, status_fill),
                (4, DATA_ALIGN_CENTER, line_fill),
                (5, DATA_ALIGN_LEFT, NEUTRAL_ROW),
                (6, DATA_ALIGN_CENTER, probe_state_fill),
                (7, DATA_ALIGN_LEFT, NEUTRAL_ROW),
                (8, DATA_ALIGN_CENTER, status_fill),
            ):
                cell = ws.cell(row=row_num, column=col)
                cell.fill = fill
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
                    # twoCell：_from 与 to 不能重合为零面积，否则 Excel 常不显示图；向下跨一行作为锚区
                    r0 = row_num - 1
                    img.anchor = TwoCellAnchor(
                        editAs="twoCell",
                        _from=AnchorMarker(col=7, colOff=0, row=r0, rowOff=0),
                        to=AnchorMarker(col=7, colOff=0, row=r0 + 1, rowOff=0),
                    )
                    ws.add_image(img)
                except (OSError, ValueError, ImportError):
                    ws.row_dimensions[row_num].height = float(ocfg.data_row_height)
            else:
                ws.row_dimensions[row_num].height = float(ocfg.data_row_height)

    ws.freeze_panes = "A2"
    if last_row >= 1:
        ws.auto_filter.ref = f"A1:H{last_row}"

    return wb
