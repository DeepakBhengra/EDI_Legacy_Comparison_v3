#!/usr/bin/env python3
"""Compare GDL and Legacy EDI X12 files and write an Excel report.

Choose each input from a local file or from the Ingram Micro SFTP server.
The report is Comparison, Summary, then the original GDL and Legacy files.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Iterable

STATUS_MATCH = "MATCH"
STATUS_MISMATCH = "MISMATCH"
STATUS_MISSING_IN_IMPULSE = "Missing in Impulse"
STATUS_MISSING_IN_GDL = "Missing in GDL"

FILL_ORANGE = "orange"
FILL_RED = "red"

SFTP_HOST = os.environ.get("SFTP_HOST", "venus.ingrammicro.com")
SFTP_PORT = int(os.environ.get("SFTP_PORT", "22"))
SFTP_USER = os.environ.get("SFTP_USER", "EDI_REPORT")
SFTP_PASSWORD_DEFAULT = os.environ.get("SFTP_PASSWORD", "")

# MX ANSI X12 trading-partner segment/element separators.
TRADING_PARTNER_CONFIG = {
    "ELO TOUCH": {"element": "|", "sub_element": "<", "segment": "~"},
    "APPLE": {"element": "~", "sub_element": ">", "segment": "?"},
    "LEXMARK": {"element": "~", "sub_element": ">", "segment": "<"},
    "HPE": {"element": "~", "sub_element": ">", "segment": "]"},
    "DELL": {"element": "*", "sub_element": "~", "segment": "¦"},
    "CISCO": {"element": "~", "sub_element": ">", "segment": "\n"},
    "SAMSUNG": {"element": "*", "sub_element": ">", "segment": "~"},
    "ACER": {"element": "~", "sub_element": ">", "segment": "*"},
    "MICROSOFT": {"element": "<", "sub_element": ">", "segment": "~"},
    "JUNIPER": {"element": "~", "sub_element": ">", "segment": "<"},
    "HPI": {"element": "~", "sub_element": ">", "segment": "]"},
    "EPSON": {"element": "*", "sub_element": "~", "segment": "\n"},
}

DEFAULT_X12_DELIMITERS = {"element": "*", "sub_element": ":", "segment": "~"}

_SEGMENT_ID = re.compile(r"^([A-Z][A-Z0-9]{1,2})")
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


@dataclass(frozen=True)
class ReportRow:
    gdl_segment: str
    legacy_segment: str
    status: str
    fill: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    rows: list[ReportRow]
    gdl_line_count: int
    legacy_line_count: int
    gdl_block_count: int = 0
    legacy_block_count: int = 0
    paired_block_count: int = 0

    @property
    def matches(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_MATCH)

    @property
    def mismatches(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_MISMATCH)

    @property
    def missing_in_impulse(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_MISSING_IN_IMPULSE)

    @property
    def missing_in_gdl(self) -> int:
        return sum(1 for row in self.rows if row.status == STATUS_MISSING_IN_GDL)


@dataclass
class LinQtyPair:
    lin: str
    qty: str | None = None


@dataclass
class StBlock:
    st: str | None = None
    bia: str | None = None
    dtm: list[str] = field(default_factory=list)
    n1: str | None = None
    n2: str | None = None
    n3: str | None = None
    n4: str | None = None
    per: str | None = None
    items: list[LinQtyPair] = field(default_factory=list)
    ctt: str | None = None
    se: str | None = None
    other: list[str] = field(default_factory=list)


@dataclass
class EdiDocument:
    isa: str | None = None
    gs: str | None = None
    blocks: list[StBlock] = field(default_factory=list)
    ge: str | None = None
    iea: str | None = None
    other: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileAuditRow:
    display_name: str
    vendor_name: str
    in_gdl: bool
    in_legacy: bool
    gdl_format: str
    legacy_format: str
    gdl_path: str
    legacy_path: str
    action: str


@dataclass(frozen=True)
class VendorComparison:
    vendor_name: str
    display_name: str
    result: ComparisonResult
    sheet_name: str


def read_segment_lines(path: Path) -> list[str]:
    """Read a segment file as individual lines, preserving inner whitespace."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if line != ""]


def timestamped_output_path(path: Path, when: datetime | None = None) -> Path:
    """Insert a local timestamp before the file suffix so each run writes a new file."""
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    suffix = path.suffix or ".xlsx"
    candidate = path.with_name(f"{path.stem}_{stamp}{suffix}")
    if candidate.exists():
        stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
        candidate = path.with_name(f"{path.stem}_{stamp}{suffix}")
    return candidate


def segment_prefix(line: str) -> str:
    """Return the X12 segment ID, regardless of the partner's element separator."""
    match = _SEGMENT_ID.match(line)
    if match:
        return match.group(1)
    return line.split("~", 1)[0]


def parse_edi_document(lines: Iterable[str]) -> EdiDocument:
    """Split an 846 dump into ISA/GS, ST-SE blocks, and GE/IEA."""
    document = EdiDocument()
    block: StBlock | None = None
    pending_item: LinQtyPair | None = None

    def close_item() -> None:
        nonlocal pending_item
        if block is not None and pending_item is not None:
            block.items.append(pending_item)
        pending_item = None

    def start_block(st_line: str) -> None:
        nonlocal block, pending_item
        close_item()
        block = StBlock(st=st_line)
        document.blocks.append(block)
        pending_item = None

    for line in lines:
        prefix = segment_prefix(line)
        if prefix == "ISA":
            document.isa = line
            block = None
        elif prefix == "GS":
            document.gs = line
            block = None
        elif prefix == "GE":
            close_item()
            block = None
            document.ge = line
        elif prefix == "IEA":
            close_item()
            block = None
            document.iea = line
        elif prefix == "ST":
            start_block(line)
        elif block is None:
            document.other.append(line)
        elif prefix == "BIA":
            close_item()
            block.bia = line
        elif prefix == "DTM":
            close_item()
            block.dtm.append(line)
        elif prefix == "N1":
            close_item()
            block.n1 = line
        elif prefix == "N2":
            close_item()
            block.n2 = line
        elif prefix == "N3":
            close_item()
            block.n3 = line
        elif prefix == "N4":
            close_item()
            block.n4 = line
        elif prefix == "PER":
            close_item()
            block.per = line
        elif prefix == "LIN":
            close_item()
            pending_item = LinQtyPair(lin=line)
        elif prefix == "QTY":
            if pending_item is not None:
                pending_item.qty = line
                close_item()
            else:
                block.items.append(LinQtyPair(lin="", qty=line))
        elif prefix == "CTT":
            close_item()
            block.ctt = line
        elif prefix == "SE":
            close_item()
            block.se = line
        else:
            close_item()
            block.other.append(line)

    close_item()
    return document


def _row(gdl: str, legacy: str, status: str) -> ReportRow:
    fill = None
    if status == STATUS_MISMATCH:
        fill = FILL_ORANGE
    elif status in {STATUS_MISSING_IN_IMPULSE, STATUS_MISSING_IN_GDL}:
        fill = FILL_RED
    return ReportRow(gdl_segment=gdl, legacy_segment=legacy, status=status, fill=fill)


def _compare_optional(gdl: str | None, legacy: str | None) -> list[ReportRow]:
    if gdl is None and legacy is None:
        return []
    if gdl is not None and legacy is not None:
        status = STATUS_MATCH if gdl == legacy else STATUS_MISMATCH
        return [_row(gdl, legacy, status)]
    if gdl is not None:
        return [_row(gdl, "", STATUS_MISSING_IN_IMPULSE)]
    return [_row("", legacy or "", STATUS_MISSING_IN_GDL)]


def _compare_lists(gdl_values: list[str], legacy_values: list[str]) -> list[ReportRow]:
    rows: list[ReportRow] = []
    limit = max(len(gdl_values), len(legacy_values))
    for index in range(limit):
        gdl = gdl_values[index] if index < len(gdl_values) else None
        legacy = legacy_values[index] if index < len(legacy_values) else None
        rows.extend(_compare_optional(gdl, legacy))
    return rows


def _emit_block_missing(block: StBlock, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(block.st)
    add(block.bia)
    for line in block.dtm:
        add(line)
    add(block.n1)
    add(block.n2)
    add(block.n3)
    add(block.n4)
    add(block.per)
    for extra in block.other:
        add(extra)
    for item in block.items:
        add(item.lin or None)
        add(item.qty)
    add(block.ctt)
    add(block.se)
    return rows


def _compare_items(gdl_items: list[LinQtyPair], legacy_items: list[LinQtyPair]) -> list[ReportRow]:
    """Match LIN/QTY pairs inside one ST-SE block. Order may differ."""
    rows: list[ReportRow] = []
    used = [False] * len(legacy_items)

    for gdl_item in gdl_items:
        found_index = None
        for index, legacy_item in enumerate(legacy_items):
            if used[index]:
                continue
            if gdl_item.lin and gdl_item.lin == legacy_item.lin:
                found_index = index
                break
        if found_index is None:
            if gdl_item.lin:
                rows.append(_row(gdl_item.lin, "", STATUS_MISSING_IN_IMPULSE))
            if gdl_item.qty:
                rows.append(_row(gdl_item.qty, "", STATUS_MISSING_IN_IMPULSE))
            continue

        used[found_index] = True
        legacy_item = legacy_items[found_index]
        rows.append(_row(gdl_item.lin, legacy_item.lin, STATUS_MATCH))
        rows.extend(_compare_optional(gdl_item.qty, legacy_item.qty))

    for index, legacy_item in enumerate(legacy_items):
        if used[index]:
            continue
        if legacy_item.lin:
            rows.append(_row("", legacy_item.lin, STATUS_MISSING_IN_GDL))
        if legacy_item.qty:
            rows.append(_row("", legacy_item.qty, STATUS_MISSING_IN_GDL))
    return rows


def _compare_blocks(gdl_block: StBlock, legacy_block: StBlock) -> list[ReportRow]:
    rows: list[ReportRow] = []
    rows.extend(_compare_optional(gdl_block.st, legacy_block.st))
    rows.extend(_compare_optional(gdl_block.bia, legacy_block.bia))
    rows.extend(_compare_lists(gdl_block.dtm, legacy_block.dtm))
    rows.extend(_compare_optional(gdl_block.n1, legacy_block.n1))
    rows.extend(_compare_optional(gdl_block.n2, legacy_block.n2))
    rows.extend(_compare_optional(gdl_block.n3, legacy_block.n3))
    rows.extend(_compare_optional(gdl_block.n4, legacy_block.n4))
    rows.extend(_compare_optional(gdl_block.per, legacy_block.per))
    rows.extend(_compare_lists(gdl_block.other, legacy_block.other))
    rows.extend(_compare_items(gdl_block.items, legacy_block.items))
    rows.extend(_compare_optional(gdl_block.ctt, legacy_block.ctt))
    rows.extend(_compare_optional(gdl_block.se, legacy_block.se))
    return rows


def compare_segments(gdl_lines: Iterable[str], legacy_lines: Iterable[str]) -> ComparisonResult:
    """Compare two 846 files: ISA/GS once, then each ST-SE block, then GE/IEA.

    ST-SE blocks with an N1 warehouse line are paired by that N1. LIN/QTY pairs
    are matched by LIN content inside the paired block, even when the order
    differs. Unmatched LIN/QTY rows are Missing in Impulse or Missing in GDL.
    """
    gdl_doc = parse_edi_document(list(gdl_lines))
    legacy_doc = parse_edi_document(list(legacy_lines))
    rows: list[ReportRow] = []

    rows.extend(_compare_optional(gdl_doc.isa, legacy_doc.isa))
    rows.extend(_compare_optional(gdl_doc.gs, legacy_doc.gs))
    rows.extend(_compare_lists(gdl_doc.other, legacy_doc.other))

    leftover_legacy: dict[str, list[int]] = {}
    for index, block in enumerate(legacy_doc.blocks):
        if block.n1:
            leftover_legacy.setdefault(block.n1, []).append(index)
    used_legacy: set[int] = set()
    paired_blocks = 0

    for gdl_block in gdl_doc.blocks:
        pair_index = None
        if gdl_block.n1:
            candidates = leftover_legacy.get(gdl_block.n1) or []
            if candidates:
                pair_index = candidates.pop(0)
        if pair_index is None:
            rows.extend(_emit_block_missing(gdl_block, "gdl"))
            continue
        used_legacy.add(pair_index)
        paired_blocks += 1
        rows.extend(_compare_blocks(gdl_block, legacy_doc.blocks[pair_index]))

    for index, legacy_block in enumerate(legacy_doc.blocks):
        if index not in used_legacy:
            rows.extend(_emit_block_missing(legacy_block, "legacy"))

    rows.extend(_compare_optional(gdl_doc.ge, legacy_doc.ge))
    rows.extend(_compare_optional(gdl_doc.iea, legacy_doc.iea))

    return ComparisonResult(
        rows=rows,
        gdl_line_count=_document_line_count(gdl_doc),
        legacy_line_count=_document_line_count(legacy_doc),
        gdl_block_count=len(gdl_doc.blocks),
        legacy_block_count=len(legacy_doc.blocks),
        paired_block_count=paired_blocks,
    )


def _document_line_count(document: EdiDocument) -> int:
    count = 0
    for value in (document.isa, document.gs, document.ge, document.iea):
        if value:
            count += 1
    count += len(document.other)
    for block in document.blocks:
        count += sum(
            1
            for value in (
                block.st,
                block.bia,
                block.n1,
                block.n2,
                block.n3,
                block.n4,
                block.per,
                block.ctt,
                block.se,
            )
            if value
        )
        count += len(block.dtm) + len(block.other)
        for item in block.items:
            count += 1 if item.lin else 0
            count += 1 if item.qty else 0
    return count


def detect_edi_format(file_content_head: str) -> str:
    head = file_content_head.strip()
    if head.startswith("ISA"):
        return "X12"
    if head.startswith("UNA") or head.startswith("UNB") or head.startswith("UNH"):
        return "EDIFACT"
    if not head:
        return "EMPTY FILE"
    return "UNKNOWN / UNSUPPORTED"


def extract_vendor_name(filename: str) -> str:
    base = os.path.basename(filename)
    parts = base.replace("-", "_").split("_")
    if not parts:
        return base.upper()
    vendor = parts[0].upper()
    if vendor == "ELO" and len(parts) > 1 and parts[1].upper() == "TOUCH":
        return "ELO TOUCH"
    return vendor


def clean_filename(name: str) -> str:
    return name.strip().replace("\r", "").replace("\n", "").lower()


def delimiters_from_isa(content: str) -> dict[str, str] | None:
    """Read X12 separators from the ISA envelope when the vendor is unknown."""
    compact = content.replace("\r", "")
    idx = compact.find("ISA")
    if idx < 0:
        return None
    window = compact[idx : idx + 200].replace("\n", "")
    if len(window) < 106 or window[:3] != "ISA":
        return None
    return {
        "element": window[3],
        "sub_element": window[104],
        "segment": window[105],
    }


def x12_delimiters_for(vendor_name: str, content: str) -> dict[str, str]:
    if vendor_name in TRADING_PARTNER_CONFIG:
        return TRADING_PARTNER_CONFIG[vendor_name]
    return delimiters_from_isa(content) or DEFAULT_X12_DELIMITERS


def parse_x12_segments(raw_content: str, vendor_name: str) -> list[str]:
    """Split a wrapped X12 interchange into one segment per list entry."""
    partner = x12_delimiters_for(vendor_name, raw_content)
    separator = partner["segment"]
    if separator == "\n":
        raw_segments = raw_content.replace("\r", "").split(separator)
    else:
        normalized = raw_content.replace("\r", "").replace("\n", "").strip()
        raw_segments = normalized.split(separator)
    return [seg.strip() for seg in raw_segments if seg.strip()]


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


def resolve_sftp_password(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_password = os.environ.get("SFTP_PASSWORD") or SFTP_PASSWORD_DEFAULT
    if env_password:
        return env_password
    return getpass("SFTP password: ")


def get_sftp_client(password: str | None = None):
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - runtime setup
        raise SystemExit(
            "paramiko is required for SFTP. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    secret = resolve_sftp_password(password)
    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=secret)
        sftp = paramiko.SFTPClient.from_transport(transport)
        return sftp, transport
    except Exception as exc:
        print(f"[ERROR] Failed to connect to SFTP: {exc}", file=sys.stderr)
        return None, None


def read_file_header_safely(sftp, file_path: str) -> str:
    try:
        with sftp.open(file_path, "rb") as handle:
            binary_data = handle.read(256)
            if not binary_data:
                return "EMPTY FILE"
            header_sample = binary_data.decode("utf-8", errors="ignore")
            return detect_edi_format(header_sample)
    except Exception as exc:
        print(f"[WARNING] Could not determine format for {file_path}: {exc}")
        return "READ ERROR / UNKNOWN"


def download_x12_segments(sftp, file_path: str, vendor_name: str) -> list[str]:
    try:
        with sftp.open(file_path, "rb") as handle:
            raw_content = handle.read().decode("utf-8", errors="ignore")
        return parse_x12_segments(raw_content, vendor_name)
    except Exception as exc:
        print(f"[ERROR] Failed to download X12 segments for {vendor_name}: {exc}")
        return []


def safe_listdir(sftp, primary_path: str) -> tuple[list[str], str]:
    try:
        return sorted(sftp.listdir(primary_path)), primary_path
    except (FileNotFoundError, OSError, IOError):
        parent, folder = os.path.split(primary_path)
        lowercase_path = f"{parent}/{folder.lower()}"
        try:
            print(
                f"[INFO] Path '{primary_path}' not found. "
                f"Trying lowercase variation: '{lowercase_path}'"
            )
            return sorted(sftp.listdir(lowercase_path)), lowercase_path
        except (FileNotFoundError, OSError, IOError) as exc:
            raise FileNotFoundError(
                f"Neither '{primary_path}' nor '{lowercase_path}' exists on server."
            ) from exc


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


def collect_file_pairs(
    sftp,
    gdl_dir: str,
    legacy_dir: str,
    gdl_files: list[str],
    legacy_files: list[str],
) -> list[FileAuditRow]:
    gdl_lookup = {clean_filename(name): name for name in gdl_files if name}
    legacy_lookup = {clean_filename(name): name for name in legacy_files if name}
    all_names = sorted(set(gdl_lookup) | set(legacy_lookup))
    rows: list[FileAuditRow] = []

    for clean_name in all_names:
        in_gdl = clean_name in gdl_lookup
        in_legacy = clean_name in legacy_lookup
        raw_gdl_name = gdl_lookup.get(clean_name)
        raw_legacy_name = legacy_lookup.get(clean_name)
        display_name = (raw_gdl_name or raw_legacy_name or clean_name).strip()
        vendor_name = extract_vendor_name(display_name)
        gdl_path = f"{gdl_dir}/{raw_gdl_name}" if raw_gdl_name else "N/A"
        legacy_path = f"{legacy_dir}/{raw_legacy_name}" if raw_legacy_name else "N/A"
        gdl_format = read_file_header_safely(sftp, gdl_path) if in_gdl else "N/A"
        legacy_format = read_file_header_safely(sftp, legacy_path) if in_legacy else "N/A"

        if not in_gdl:
            action = "Missing in New GDL Folder"
        elif not in_legacy:
            action = "Missing in Legacy Folder"
        elif gdl_format != "X12" or legacy_format != "X12":
            action = "SKIPPED (X12 only)"
        else:
            action = "Compared"

        rows.append(
            FileAuditRow(
                display_name=display_name,
                vendor_name=vendor_name,
                in_gdl=in_gdl,
                in_legacy=in_legacy,
                gdl_format=gdl_format,
                legacy_format=legacy_format,
                gdl_path=gdl_path,
                legacy_path=legacy_path,
                action=action,
            )
        )
    return rows


def compare_x12_pairs(sftp, audit_rows: list[FileAuditRow]) -> list[VendorComparison]:
    used_sheets: set[str] = {"File Audit", "Summary"}
    comparisons: list[VendorComparison] = []
    for row in audit_rows:
        if row.action != "Compared":
            continue
        print(f"[COMPARING] {row.vendor_name} ({row.display_name})")
        gdl_segs = download_x12_segments(sftp, row.gdl_path, row.vendor_name)
        legacy_segs = download_x12_segments(sftp, row.legacy_path, row.vendor_name)
        result = compare_segments(gdl_segs, legacy_segs)
        sheet_name = unique_sheet_name(row.vendor_name, used_sheets)
        comparisons.append(
            VendorComparison(
                vendor_name=row.vendor_name,
                display_name=row.display_name,
                result=result,
                sheet_name=sheet_name,
            )
        )
        print(
            f"  MATCH={result.matches:,}  MISMATCH={result.mismatches:,}  "
            f"Missing Impulse={result.missing_in_impulse:,}  "
            f"Missing GDL={result.missing_in_gdl:,}"
        )
    return comparisons


def list_local_input_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )


def annotate_sftp_files(sftp, directory: str, names: list[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for name in names:
        if not name:
            continue
        path = f"{directory}/{name}"
        edi_format = read_file_header_safely(sftp, path)
        rows.append((name, edi_format, path))
    return rows


def prompt_choice(
    title: str,
    options: list[tuple[str, str]],
    input_func=input,
) -> str:
    while True:
        print(title)
        for index, (label, _value) in enumerate(options, start=1):
            print(f"[{index}] {label}")
        raw = input_func(f"Select (1-{len(options)}): ").strip()
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(options):
                return options[choice - 1][1]
        print("[Invalid Input] Please enter a listed number.\n")


def prompt_country(input_func=input) -> str:
    return prompt_choice(
        "Select Country Profile:",
        [("Mexico (MX)", "MX"), ("Singapore (SG)", "SG")],
        input_func=input_func,
    )


def prompt_report_type(input_func=input) -> str:
    return prompt_choice(
        "\nSelect Report Type:",
        [("Inventory (INV - EDI 846)", "INV"), ("Point of Sale (POS - EDI 867)", "POS")],
        input_func=input_func,
    )


def prompt_input_source(label: str, input_func=input) -> str:
    return prompt_choice(
        f"\nSelect {label} input source:",
        [("Local file", "local"), ("SFTP server", "sftp")],
        input_func=input_func,
    )


def prompt_local_file(label: str, directory: Path, input_func=input) -> Path:
    files = list_local_input_files(directory)
    options: list[tuple[str, str]] = [(str(path), str(path)) for path in files]
    options.append(("Enter a custom path", "__custom__"))
    selected = prompt_choice(f"\nSelect {label} file:", options, input_func=input_func)
    if selected != "__custom__":
        return Path(selected)
    while True:
        typed = input_func(f"Enter {label} file path: ").strip()
        path = Path(typed).expanduser()
        if path.is_file():
            return path
        print(f"[Invalid Input] File not found: {path}\n")


def prompt_sftp_file(
    label: str,
    entries: list[tuple[str, str, str]],
    input_func=input,
) -> tuple[str, str, str]:
    if not entries:
        raise FileNotFoundError(f"No files available to select for {label}.")
    options = [
        (f"{name}  [{edi_format}]", name)
        for name, edi_format, _path in entries
    ]
    lookup = {name: (name, edi_format, path) for name, edi_format, path in entries}
    while True:
        selected = prompt_choice(f"\nSelect {label} file:", options, input_func=input_func)
        name, edi_format, path = lookup[selected]
        if edi_format != "X12":
            print(f"[Invalid Input] {name} is {edi_format}. Choose an X12 file.\n")
            continue
        return name, edi_format, path


def lookup_sftp_entry(
    entries: list[tuple[str, str, str]],
    filename: str,
) -> tuple[str, str, str] | None:
    wanted = clean_filename(filename)
    for name, edi_format, path in entries:
        if clean_filename(name) == wanted or name == filename:
            return name, edi_format, path
    return None


def load_local_segments(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line != ""]
    if detect_edi_format(text) == "X12" and len(lines) <= 3:
        return parse_x12_segments(text, extract_vendor_name(path.name))
    return lines


def print_comparison_stats(result: ComparisonResult, report_path: Path) -> None:
    print()
    print("Comparison complete")
    print(f"  GDL ST-SE blocks:          {result.gdl_block_count:,}")
    print(f"  Legacy ST-SE blocks:       {result.legacy_block_count:,}")
    print(f"  Paired warehouse blocks:   {result.paired_block_count:,}")
    print(f"  MATCH:                     {result.matches:,}")
    print(f"  MISMATCH:                  {result.mismatches:,}")
    print(f"  Missing in Impulse:        {result.missing_in_impulse:,}")
    print(f"  Missing in GDL:            {result.missing_in_gdl:,}")
    print(f"  Report rows:               {len(result.rows):,}")
    print(f"  Excel report:              {report_path}")


def run_two_file_comparison(
    gdl_lines: list[str],
    legacy_lines: list[str],
    output_path: Path,
    gdl_source: str,
    legacy_source: str,
) -> int:
    print(f"Comparing {len(gdl_lines):,} GDL lines with {len(legacy_lines):,} Legacy lines...")
    result = compare_segments(gdl_lines, legacy_lines)
    report_path = timestamped_output_path(output_path)
    write_excel_report(
        result,
        report_path,
        gdl_lines=gdl_lines,
        legacy_lines=legacy_lines,
        gdl_source=gdl_source,
        legacy_source=legacy_source,
    )
    print_comparison_stats(result, report_path)
    return 0


def resolve_sftp_folder(sftp, country: str, report_type: str, side: str) -> tuple[list[str], str]:
    if side == "gdl":
        base = f"/GDL/{country}/{report_type}"
    else:
        base = f"/ECC_IMPULSE/{country}/{report_type}"
    return safe_listdir(sftp, base)


def load_sftp_selected_file(
    sftp,
    country: str,
    report_type: str,
    side: str,
    filename: str | None,
    input_func=input,
) -> tuple[str, list[str]]:
    label = "GDL" if side == "gdl" else "Legacy"
    names, directory = resolve_sftp_folder(sftp, country, report_type, side)
    print(f"{label} SFTP folder: {directory} ({len(names)} files)")
    entries = annotate_sftp_files(sftp, directory, names)
    if filename:
        match = lookup_sftp_entry(entries, filename)
        if match is None:
            raise FileNotFoundError(f"{label} file not found on SFTP: {filename}")
        name, edi_format, path = match
        if edi_format != "X12":
            raise ValueError(f"{label} file {name} is {edi_format}, not X12.")
    else:
        name, edi_format, path = prompt_sftp_file(label, entries, input_func=input_func)
    vendor = extract_vendor_name(name)
    segments = download_x12_segments(sftp, path, vendor)
    return f"sftp:{path}", segments


def process_sftp_comparison(
    country: str,
    report_type: str,
    output_path: Path,
    password: str | None = None,
    sftp=None,
    transport=None,
    gdl_file: str | None = None,
    legacy_file: str | None = None,
    compare_all: bool = False,
    input_func=input,
) -> int:
    close_client = False
    if sftp is None:
        sftp, transport = get_sftp_client(password)
        close_client = True
    if not sftp:
        return 1

    print(f"\n--- Processing Profile: {country} - {report_type} (X12 only) ---")

    try:
        if not compare_all:
            try:
                gdl_source, gdl_lines = load_sftp_selected_file(
                    sftp, country, report_type, "gdl", gdl_file, input_func=input_func
                )
                legacy_source, legacy_lines = load_sftp_selected_file(
                    sftp, country, report_type, "legacy", legacy_file, input_func=input_func
                )
            except (FileNotFoundError, ValueError) as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
            return run_two_file_comparison(
                gdl_lines,
                legacy_lines,
                output_path,
                gdl_source,
                legacy_source,
            )

        gdl_base = f"/GDL/{country}/{report_type}"
        legacy_base = f"/ECC_IMPULSE/{country}/{report_type}"
        try:
            gdl_files, gdl_dir = safe_listdir(sftp, gdl_base)
            legacy_files, legacy_dir = safe_listdir(sftp, legacy_base)
        except FileNotFoundError as exc:
            print(f"[ERROR] Directory scan failed: {exc}", file=sys.stderr)
            return 1

        print(f"Scanning GDL folder   : {gdl_dir} (Found {len(gdl_files)} files)")
        print(f"Scanning Legacy folder: {legacy_dir} (Found {len(legacy_files)} files)\n")
        if not gdl_files and not legacy_files:
            print("[INFO] Both folders are empty. The Excel File Audit sheet will have headers only.")

        audit_rows = collect_file_pairs(sftp, gdl_dir, legacy_dir, gdl_files, legacy_files)
        vendor_comparisons = compare_x12_pairs(sftp, audit_rows)
        report_path = timestamped_output_path(output_path)
        write_sftp_excel_report(
            audit_rows,
            vendor_comparisons,
            report_path,
            country,
            report_type,
        )
        print("\n[SUCCESS] X12 comparison finished.")
        print(f"  Files audited:             {len(audit_rows)}")
        print(f"  X12 pairs compared:        {len(vendor_comparisons)}")
        print(f"  Excel report:              {report_path}")
        return 0
    finally:
        if close_client:
            try:
                sftp.close()
            except Exception:
                pass
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Compare one GDL file with one Legacy file. Each file can come from "
            "a local path or from SFTP. The Excel report includes Comparison, "
            "Summary, GDL File, and Legacy File sheets."
        )
    )
    parser.add_argument(
        "--source",
        choices=("local", "sftp"),
        help="Use this source for both GDL and Legacy files.",
    )
    parser.add_argument(
        "--gdl-source",
        choices=("local", "sftp"),
        help="Source for the GDL file: local or sftp.",
    )
    parser.add_argument(
        "--legacy-source",
        choices=("local", "sftp"),
        help="Source for the Legacy file: local or sftp.",
    )
    parser.add_argument(
        "--gdl",
        type=Path,
        default=None,
        help="Path to a local GDL segment file.",
    )
    parser.add_argument(
        "--legacy",
        type=Path,
        default=None,
        help="Path to a local Legacy / Impulse segment file.",
    )
    parser.add_argument(
        "--gdl-file",
        default=None,
        help="Filename to pick from the SFTP GDL folder.",
    )
    parser.add_argument(
        "--legacy-file",
        default=None,
        help="Filename to pick from the SFTP Legacy folder.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Compare the bundled sample files in data/.",
    )
    parser.add_argument(
        "--sftp",
        action="store_true",
        help="Load files from SFTP (prompts for country, report, and filenames).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compare every matching X12 pair on SFTP instead of picking two files.",
    )
    parser.add_argument(
        "--country",
        choices=("MX", "SG"),
        help="SFTP country folder: MX or SG.",
    )
    parser.add_argument(
        "--report",
        choices=("INV", "POS"),
        help="SFTP report folder: INV (846) or POS (867).",
    )
    parser.add_argument(
        "--sftp-password",
        default=None,
        help="SFTP password. Defaults to SFTP_PASSWORD env var, then a prompt.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=repo_root / "reports" / "segment_comparison.xlsx",
        help="Base path for the Excel report. A timestamp is added to the filename on each run.",
    )
    return parser.parse_args(argv)


def resolve_side_source(args: argparse.Namespace, side: str, input_func=input) -> str:
    explicit_path = args.gdl if side == "gdl" else args.legacy
    remote_name = args.gdl_file if side == "gdl" else args.legacy_file
    side_source = args.gdl_source if side == "gdl" else args.legacy_source
    label = "GDL" if side == "gdl" else "Legacy"

    if explicit_path is not None:
        return "local"
    if remote_name:
        return "sftp"
    if side_source:
        return side_source
    if args.source:
        return args.source
    if args.local:
        return "local"
    if args.sftp or args.all or args.country or args.report:
        return "sftp"
    return prompt_input_source(label, input_func=input_func)


def run_local_comparison(gdl_path: Path, legacy_path: Path, output_path: Path) -> int:
    if not gdl_path.is_file():
        print(f"GDL segment file not found: {gdl_path}", file=sys.stderr)
        return 1
    if not legacy_path.is_file():
        print(f"Legacy segment file not found: {legacy_path}", file=sys.stderr)
        return 1

    print(f"Reading GDL segments from {gdl_path}")
    gdl_lines = load_local_segments(gdl_path)
    print(f"Reading Legacy segments from {legacy_path}")
    legacy_lines = load_local_segments(legacy_path)
    return run_two_file_comparison(
        gdl_lines,
        legacy_lines,
        output_path,
        str(gdl_path),
        str(legacy_path),
    )


def open_sftp_or_fail(password: str | None):
    sftp, transport = get_sftp_client(password)
    if not sftp:
        return None, None
    return sftp, transport


def main(argv: list[str] | None = None, input_func=input) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parent
    data_dir = repo_root / "data"

    print("=" * 45)
    print("     EDI X12 SEGMENT COMPARISON")
    print("=" * 45)

    if args.all:
        country = args.country or prompt_country(input_func=input_func)
        report_type = args.report or prompt_report_type(input_func=input_func)
        output_path = args.output
        if output_path.name == "segment_comparison.xlsx":
            output_path = output_path.with_name(
                f"segment_comparison_{country}_{report_type}_all.xlsx"
            )
        return process_sftp_comparison(
            country,
            report_type,
            output_path,
            password=args.sftp_password,
            compare_all=True,
            input_func=input_func,
        )

    if args.local and args.gdl is None and args.legacy is None:
        return run_local_comparison(
            data_dir / "GDL_Segment.txt",
            data_dir / "Legacy_Segment.txt",
            args.output,
        )

    gdl_source = resolve_side_source(args, "gdl", input_func=input_func)
    legacy_source = resolve_side_source(args, "legacy", input_func=input_func)

    country = args.country
    report_type = args.report
    if gdl_source == "sftp" or legacy_source == "sftp":
        country = country or prompt_country(input_func=input_func)
        report_type = report_type or prompt_report_type(input_func=input_func)

    sftp = None
    transport = None
    try:
        if gdl_source == "sftp" or legacy_source == "sftp":
            sftp, transport = open_sftp_or_fail(args.sftp_password)
            if not sftp:
                return 1

        if gdl_source == "local":
            gdl_path = args.gdl or prompt_local_file("GDL", data_dir, input_func=input_func)
            if not gdl_path.is_file():
                print(f"GDL segment file not found: {gdl_path}", file=sys.stderr)
                return 1
            print(f"Reading GDL segments from {gdl_path}")
            gdl_lines = load_local_segments(gdl_path)
            gdl_label = str(gdl_path)
        else:
            assert country is not None and report_type is not None and sftp is not None
            try:
                gdl_label, gdl_lines = load_sftp_selected_file(
                    sftp, country, report_type, "gdl", args.gdl_file, input_func=input_func
                )
            except (FileNotFoundError, ValueError) as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
            print(f"Reading GDL segments from {gdl_label}")

        if legacy_source == "local":
            legacy_path = args.legacy or prompt_local_file(
                "Legacy", data_dir, input_func=input_func
            )
            if not legacy_path.is_file():
                print(f"Legacy segment file not found: {legacy_path}", file=sys.stderr)
                return 1
            print(f"Reading Legacy segments from {legacy_path}")
            legacy_lines = load_local_segments(legacy_path)
            legacy_label = str(legacy_path)
        else:
            assert country is not None and report_type is not None and sftp is not None
            try:
                legacy_label, legacy_lines = load_sftp_selected_file(
                    sftp,
                    country,
                    report_type,
                    "legacy",
                    args.legacy_file,
                    input_func=input_func,
                )
            except (FileNotFoundError, ValueError) as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 1
            print(f"Reading Legacy segments from {legacy_label}")
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass

    output_path = args.output
    if (
        output_path.name == "segment_comparison.xlsx"
        and (gdl_source == "sftp" or legacy_source == "sftp")
        and country
        and report_type
    ):
        output_path = output_path.with_name(f"segment_comparison_{country}_{report_type}.xlsx")
    return run_two_file_comparison(
        gdl_lines,
        legacy_lines,
        output_path,
        gdl_label,
        legacy_label,
    )


if __name__ == "__main__":
    raise SystemExit(main())
