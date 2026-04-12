"""Excel 报告：表头、状态文本、底色、嵌入截图。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from domain_test.browser_check import UrlCheckResult, format_cell_status
from domain_test.config import AppConfig

GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
YELLOW = PatternFill("solid", fgColor="FFF2CC")


def _fill_for_result(result: UrlCheckResult) -> PatternFill:
    if result.label == "success":
        return GREEN
    if result.label == "blocked":
        return YELLOW
    return RED


def build_workbook(
    cfg: AppConfig,
    rows: Sequence[tuple[str, list[UrlCheckResult]]],
    url_headers: list[str],
) -> Workbook:
    """
    rows: 每项为 (公网 IP, 与该 IP 下列顺序与 url_headers 对齐的检测结果列表)
    """
    wb = Workbook()
    ws = wb.active
    assert ws is not None

    header_row = ["公网IP"] + url_headers
    ws.append(header_row)

    ocfg = cfg.output
    data_row_start = 2

    for r_idx, (pub_ip, results) in enumerate(rows, start=0):
        row_num = data_row_start + r_idx
        ws.cell(row=row_num, column=1, value=pub_ip)
        for c_idx, res in enumerate(results, start=2):
            text = format_cell_status(res)
            cell = ws.cell(row=row_num, column=c_idx, value=text)
            cell.fill = _fill_for_result(res)

            sp = res.screenshot_path
            if sp and Path(sp).is_file():
                try:
                    img = XLImage(sp)
                    img.width = ocfg.embed_screenshot_max_width
                    img.height = ocfg.embed_screenshot_max_height
                    anchor = ws.cell(row=row_num, column=c_idx).coordinate
                    ws.add_image(img, anchor)
                except OSError:
                    pass

        ws.row_dimensions[row_num].height = ocfg.data_row_height

    for col in range(1, len(header_row) + 1):
        letter = get_column_letter(col)
        ws.column_dimensions[letter].width = 28 if col > 1 else 18

    return wb
