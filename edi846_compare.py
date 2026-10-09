#!/usr/bin/env python3
"""Compare GDL and Legacy X12 846 segment lists.

Source-agnostic: both local files and SFTP downloads are reduced to segment
lines, then compared here with ISA/GS, N1 warehouse-block pairing, and LIN/QTY
matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from x12_format import segment_prefix

STATUS_MATCH = "MATCH"
STATUS_MISMATCH = "MISMATCH"
STATUS_MISSING_IN_IMPULSE = "Missing in Impulse"
STATUS_MISSING_IN_GDL = "Missing in GDL"

FILL_ORANGE = "orange"
FILL_RED = "red"


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


def compare_loaded_segments(
    gdl_lines: Iterable[str],
    legacy_lines: Iterable[str],
) -> ComparisonResult:
    """Dispatch GDL vs Legacy comparison for X12 846 or EDIFACT INVRPT."""
    from x12_format import detect_edi_format

    gdl_list = list(gdl_lines)
    legacy_list = list(legacy_lines)
    gdl_fmt = detect_edi_format(next((line for line in gdl_list if line.strip()), ""))
    legacy_fmt = detect_edi_format(next((line for line in legacy_list if line.strip()), ""))
    if gdl_fmt == "EDIFACT" and legacy_fmt == "EDIFACT":
        from edifact_invrpt_compare import compare_edifact_invrpt

        return compare_edifact_invrpt(gdl_list, legacy_list)
    if gdl_fmt == "X12" and legacy_fmt == "X12":
        return compare_segments(gdl_list, legacy_list)
    if gdl_fmt in {"EMPTY FILE", "UNKNOWN / UNSUPPORTED"} and legacy_fmt in {
        "EMPTY FILE",
        "UNKNOWN / UNSUPPORTED",
        "X12",
    }:
        return compare_segments(gdl_list, legacy_list)
    if gdl_fmt == "X12" and legacy_fmt in {"EMPTY FILE", "UNKNOWN / UNSUPPORTED"}:
        return compare_segments(gdl_list, legacy_list)
    if gdl_fmt != legacy_fmt:
        return ComparisonResult(
            rows=[
                ReportRow(
                    gdl_segment=f"Format: {gdl_fmt}",
                    legacy_segment=f"Format: {legacy_fmt}",
                    status=STATUS_MISMATCH,
                    fill=FILL_ORANGE,
                )
            ],
            gdl_line_count=len(gdl_list),
            legacy_line_count=len(legacy_list),
        )
    return compare_segments(gdl_list, legacy_list)


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
