#!/usr/bin/env python3
"""Excel report writers for two-file and bulk SFTP comparisons."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from edi846_compare import (
    FILL_ORANGE,
    FILL_RED,
    ComparisonResult,
)
from sftp_client import FileAuditRow, VendorComparison

_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def timestamped_output_path(path: Path, when: datetime | None = None) -> Path:
    """Insert a local timestamp before the file suffix so each run writes a new file."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    suffix = path.suffix or ".xlsx"
    candidate = path.with_name(f"{path.stem}_{stamp}{suffix}")
    if candidate.exists():
        stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
        candidate = path.with_name(f"{path.stem}_{stamp}{suffix}")
    return candidate


def unique_sheet_name(raw_name: str, used: set[str]) -> str:
    cleaned = _INVALID_SHEET_CHARS.sub(" ", raw_name).strip() or "Vendor"
    base = cleaned[:31]
    candidate = base
    suffix = 2
    while candidate in used:
        tail = f"_{suffix}"
        candidate = f"{base[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _xlsx_formats(workbook) -> dict[str, object]:
    return {
        "header": workbook.add_format(
            {
                "bold": True,
                "bg_color": "#1F4E79",
                "font_color": "#FFFFFF",
                "border": 1,
                "valign": "vcenter",
                "align": "center",
            }
        ),
        "match": workbook.add_format({"border": 1, "valign": "top", "text_wrap": True}),
        "orange": workbook.add_format(
            {"border": 1, "valign": "top", "text_wrap": True, "bg_color": "#FFC000"}
        ),
        "red": workbook.add_format(
            {
                "border": 1,
                "valign": "top",
                "text_wrap": True,
                "bg_color": "#FF0000",
                "font_color": "#FFFFFF",
            }
        ),
        "label": workbook.add_format({"bold": True, "border": 1, "bg_color": "#D9E2F3"}),
        "value": workbook.add_format({"border": 1}),
        "orange_value": workbook.add_format({"border": 1, "bg_color": "#FFC000"}),
        "red_value": workbook.add_format(
            {"border": 1, "bg_color": "#FF0000", "font_color": "#FFFFFF"}
        ),
    }


def _write_comparison_sheet(workbook, sheet_name: str, result: ComparisonResult, formats: dict[str, object]) -> None:
    detail = workbook.add_worksheet(sheet_name)
    detail.write(0, 0, "GDL Segment", formats["header"])
    detail.write(0, 1, "Legacy Segment", formats["header"])
    detail.write(0, 2, "status", formats["header"])
    detail.freeze_panes(1, 0)
    detail.set_column(0, 1, 85)
    detail.set_column(2, 2, 24)
    detail.set_row(0, 22)
    last_data_row = max(len(result.rows), 1)
    detail.autofilter(0, 0, last_data_row, 2)

    for row_number, row in enumerate(result.rows, start=1):
        if row.fill == FILL_ORANGE:
            cell_fmt = formats["orange"]
        elif row.fill == FILL_RED:
            cell_fmt = formats["red"]
        else:
            cell_fmt = formats["match"]
        detail.write(row_number, 0, row.gdl_segment, cell_fmt)
        detail.write(row_number, 1, row.legacy_segment, cell_fmt)
        detail.write(row_number, 2, row.status, cell_fmt)


def _write_metrics_sheet(
    workbook,
    sheet_name: str,
    result: ComparisonResult,
    formats: dict[str, object],
) -> None:
    summary = workbook.add_worksheet(sheet_name)
    summary.set_column(0, 0, 36)
    summary.set_column(1, 1, 18)
    summary_rows = [
        ("GDL lines", result.gdl_line_count, formats["value"]),
        ("Legacy lines", result.legacy_line_count, formats["value"]),
        ("GDL ST-SE blocks", result.gdl_block_count, formats["value"]),
        ("Legacy ST-SE blocks", result.legacy_block_count, formats["value"]),
        ("Paired warehouse blocks", result.paired_block_count, formats["value"]),
        ("MATCH", result.matches, formats["value"]),
        ("MISMATCH", result.mismatches, formats["orange_value"]),
        ("Missing in Impulse", result.missing_in_impulse, formats["red_value"]),
        ("Missing in GDL", result.missing_in_gdl, formats["red_value"]),
        ("Total report rows", len(result.rows), formats["value"]),
    ]
    summary.write(0, 0, "Metric", formats["header"])
    summary.write(0, 1, "Count", formats["header"])
    for index, (label, value, fmt) in enumerate(summary_rows, start=1):
        summary.write(index, 0, label, formats["label"])
        summary.write(index, 1, value, fmt)


def _write_source_sheet(
    workbook,
    sheet_name: str,
    source_label: str,
    lines: Iterable[str],
    formats: dict[str, object],
) -> None:
    """Dump the original GDL or Legacy segments onto their own sheet."""
    segments = list(lines)
    sheet = workbook.add_worksheet(sheet_name)
    sheet.write(0, 0, "Source", formats["header"])
    sheet.write(0, 1, source_label, formats["value"])
    sheet.write(1, 0, "Line", formats["header"])
    sheet.write(1, 1, "Segment", formats["header"])
    sheet.freeze_panes(2, 0)
    sheet.set_column(0, 0, 10)
    sheet.set_column(1, 1, 120)
    sheet.set_row(1, 22)
    for index, line in enumerate(segments, start=1):
        sheet.write(index + 1, 0, index, formats["value"])
        sheet.write(index + 1, 1, line, formats["match"])
    last_row = max(len(segments) + 1, 2)
    sheet.autofilter(1, 0, last_row, 1)


def write_excel_report(
    result: ComparisonResult,
    output_path: Path,
    gdl_lines: Iterable[str] | None = None,
    legacy_lines: Iterable[str] | None = None,
    gdl_source: str | None = None,
    legacy_source: str | None = None,
) -> None:
    """Write Comparison, Summary, then the original GDL and Legacy files."""
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - exercised in runtime setups
        raise SystemExit(
            "xlsxwriter is required. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(output_path))
    formats = _xlsx_formats(workbook)
    _write_comparison_sheet(workbook, "Comparison", result, formats)
    _write_metrics_sheet(workbook, "Summary", result, formats)
    if gdl_lines is not None:
        _write_source_sheet(
            workbook,
            "GDL File",
            gdl_source or "GDL",
            gdl_lines,
            formats,
        )
    if legacy_lines is not None:
        _write_source_sheet(
            workbook,
            "Legacy File",
            legacy_source or "Legacy",
            legacy_lines,
            formats,
        )
    workbook.close()


def write_sftp_excel_report(
    audit_rows: list[FileAuditRow],
    vendor_comparisons: list[VendorComparison],
    output_path: Path,
    country: str,
    report_type: str,
) -> None:
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - runtime setup
        raise SystemExit(
            "xlsxwriter is required. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(output_path))
    formats = _xlsx_formats(workbook)

    audit = workbook.add_worksheet("File Audit")
    audit_headers = [
        "Vendor File Name",
        "Vendor",
        "In GDL (New System)",
        "In Legacy (ECC/Impulse)",
        "GDL EDI Format",
        "Legacy EDI Format",
        "Action",
        "GDL Path",
        "Legacy Path",
    ]
    for col, header in enumerate(audit_headers):
        audit.write(0, col, header, formats["header"])
    audit.freeze_panes(1, 0)
    audit.set_column(0, 0, 40)
    audit.set_column(1, 1, 16)
    audit.set_column(2, 5, 22)
    audit.set_column(6, 6, 36)
    audit.set_column(7, 8, 50)
    audit.set_row(0, 22)
    last_audit_row = max(len(audit_rows), 1)
    audit.autofilter(0, 0, last_audit_row, len(audit_headers) - 1)

    for row_number, row in enumerate(audit_rows, start=1):
        values = [
            row.display_name,
            row.vendor_name,
            "YES" if row.in_gdl else "NO",
            "YES" if row.in_legacy else "NO",
            row.gdl_format,
            row.legacy_format,
            row.action,
            row.gdl_path,
            row.legacy_path,
        ]
        cell_fmt = formats["match"]
        if "SKIPPED" in row.action or "Missing" in row.action:
            cell_fmt = formats["red"]
        elif row.action.startswith("Compared"):
            cell_fmt = formats["match"]
        for col, value in enumerate(values):
            audit.write(row_number, col, value, cell_fmt)

    overview = workbook.add_worksheet("Summary")
    overview.set_column(0, 0, 36)
    overview.set_column(1, 8, 18)
    overview.write(0, 0, "Vendor File", formats["header"])
    overview.write(0, 1, "Vendor", formats["header"])
    overview.write(0, 2, "MATCH", formats["header"])
    overview.write(0, 3, "MISMATCH", formats["header"])
    overview.write(0, 4, "Missing in Impulse", formats["header"])
    overview.write(0, 5, "Missing in GDL", formats["header"])
    overview.write(0, 6, "Paired blocks", formats["header"])
    overview.write(0, 7, "GDL lines", formats["header"])
    overview.write(0, 8, "Legacy lines", formats["header"])
    overview.freeze_panes(1, 0)
    overview.write(1, 0, f"Profile {country} / {report_type}", formats["label"])
    overview.write(1, 1, f"{len(vendor_comparisons)} X12 pair(s)", formats["value"])

    for index, item in enumerate(vendor_comparisons, start=2):
        result = item.result
        overview.write(index, 0, item.display_name, formats["label"])
        overview.write(index, 1, item.vendor_name, formats["value"])
        overview.write(index, 2, result.matches, formats["value"])
        overview.write(index, 3, result.mismatches, formats["orange_value"])
        overview.write(index, 4, result.missing_in_impulse, formats["red_value"])
        overview.write(index, 5, result.missing_in_gdl, formats["red_value"])
        overview.write(index, 6, result.paired_block_count, formats["value"])
        overview.write(index, 7, result.gdl_line_count, formats["value"])
        overview.write(index, 8, result.legacy_line_count, formats["value"])

    for item in vendor_comparisons:
        _write_comparison_sheet(workbook, item.sheet_name, item.result, formats)

    workbook.close()
