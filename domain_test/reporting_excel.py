"""Excel 报告：纵向每 URL 一行、状态底色、嵌入截图（固定高度按比例缩放宽）。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import PatternFill

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


def _px_to_row_height_points(px: float) -> float:
    """Excel 行高为磅；按 96dpi 将像素近似为磅。"""
    return px * 72.0 / 96.0


def _embedded_pixel_size(image_path: Path, target_height_px: int) -> tuple[int, int]:
    """
    嵌入图固定高度 target_height_px，宽度按原图宽高比缩放。
    返回 (width_px, height_px)。
    """
    try:
        from PIL import Image as PILImage

        with PILImage.open(image_path) as im:
            w, h = im.size
        if h <= 0:
            return target_height_px, target_height_px
        tw = max(1, round(w * target_height_px / h))
        return tw, target_height_px
    except Exception:
        return target_height_px, target_height_px


def build_workbook(
    cfg: AppConfig,
    rows: Sequence[tuple[str, list[UrlCheckResult]]],
    url_headers: list[str],
) -> Workbook:
    """
    纵向表：每行一条 URL（同一公网 IP 可占多行）。
    rows: (公网 IP, 与 url_headers 顺序对齐的 UrlCheckResult 列表)
    """
    wb = Workbook()
    ws = wb.active
    assert ws is not None

    ocfg = cfg.output
    target_h = int(ocfg.embed_screenshot_max_height)
    if target_h <= 0:
        target_h = 180

    ws.append(["公网IP", "URL", "结果", "截图"])
    for col_letter, width in (("A", 14), ("B", 56), ("C", 42), ("D", 18)):
        ws.column_dimensions[col_letter].width = width

    def _bump_screenshot_col_width(tw_px: int) -> None:
        # 近似：1 个 Excel「字符列宽」≈ 7 px；上限避免过宽
        wch = min(90.0, max(18.0, tw_px / 7.0 + 2.0))
        cur = ws.column_dimensions["D"].width or 18.0
        if wch > cur:
            ws.column_dimensions["D"].width = wch

    for pub_ip, results in rows:
        for url, res in zip(url_headers, results):
            ws.append([pub_ip, url, format_cell_status(res), ""])
            row_num = ws.max_row
            status_cell = ws.cell(row=row_num, column=3)
            status_cell.fill = _fill_for_result(res)

            sp = res.screenshot_path
            if sp and Path(sp).is_file():
                p = Path(sp)
                try:
                    img = XLImage(str(p))
                    tw, th = _embedded_pixel_size(p, target_h)
                    img.width = tw
                    img.height = th
                    _bump_screenshot_col_width(tw)
                    ws.add_image(img, f"D{row_num}")
                    ws.row_dimensions[row_num].height = _px_to_row_height_points(th)
                except OSError:
                    ws.row_dimensions[row_num].height = float(ocfg.data_row_height)
            else:
                ws.row_dimensions[row_num].height = float(ocfg.data_row_height)

    return wb
