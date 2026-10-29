#!/usr/bin/env python3
"""Compare GDL and Legacy X12 867 POS (Product Transfer and Resale) files.

Mirrors the 846 inventory rules: ISA/GS once, then PTD loops paired by the
ship-to N1, then QTY/LIN/UIT/PID/DTM items matched by LIN inside that PTD.
Item and PTD order may differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from edi846_compare import (
    FILL_ORANGE,
    FILL_RED,
    STATUS_MATCH,
    STATUS_MISSING_IN_GDL,
    STATUS_MISSING_IN_IMPULSE,
    STATUS_MISMATCH,
    ComparisonResult,
    ReportRow,
)
from x12_format import segment_prefix, x12_element


@dataclass
class PosParty:
    n1: str | None = None
    n3: str | None = None
    n4: str | None = None
    extra: list[str] = field(default_factory=list)


@dataclass
class PosItem:
    qty: str | None = None
    lin: str | None = None
    uit: str | None = None
    pid: str | None = None
    dtm: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


@dataclass
class PtdBlock:
    ptd: str | None = None
    ship_to: PosParty = field(default_factory=PosParty)
    bill_to: PosParty = field(default_factory=PosParty)
    items: list[PosItem] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def match_key(self) -> str:
        """Pair PTD loops by the ship-to N1, the 846 warehouse analog."""
        return self.ship_to.n1 or ""


@dataclass
class PosDocument:
    isa: str | None = None
    gs: str | None = None
    st: str | None = None
    bpt: str | None = None
    header_dtm: list[str] = field(default_factory=list)
    distributor: PosParty = field(default_factory=PosParty)
    header_other: list[str] = field(default_factory=list)
    ptd_blocks: list[PtdBlock] = field(default_factory=list)
    ctt: str | None = None
    se: str | None = None
    ge: str | None = None
    iea: str | None = None
    other: list[str] = field(default_factory=list)


def parse_pos_document(lines: Iterable[str]) -> PosDocument:
    """Split an 867 dump into envelope, header DS party, and PTD item loops."""
    document = PosDocument()
    block: PtdBlock | None = None
    party: PosParty | None = None
    item: PosItem | None = None

    def close_item() -> None:
        nonlocal item
        if block is not None and item is not None:
            block.items.append(item)
        item = None

    def attach_party() -> None:
        nonlocal party
        party = None

    def start_ptd(line: str) -> None:
        nonlocal block, party, item
        close_item()
        attach_party()
        block = PtdBlock(ptd=line)
        document.ptd_blocks.append(block)

    def start_item(qty_line: str) -> None:
        nonlocal item, party
        close_item()
        attach_party()
        if block is None:
            return
        item = PosItem(qty=qty_line)

    def start_party(n1_line: str) -> PosParty:
        nonlocal party, item
        close_item()
        qualifier = x12_element(n1_line, 0)
        if block is None:
            if qualifier == "DS":
                document.distributor.n1 = n1_line
                party = document.distributor
                return party
            document.header_other.append(n1_line)
            party = None
            return document.distributor
        if qualifier == "ST":
            block.ship_to.n1 = n1_line
            party = block.ship_to
        elif qualifier == "BT":
            block.bill_to.n1 = n1_line
            party = block.bill_to
        else:
            block.extra.append(n1_line)
            party = None
        return party if party is not None else block.ship_to

    for line in lines:
        if not line:
            continue
        prefix = segment_prefix(line)
        if prefix == "ISA":
            document.isa = line
            block = None
            party = None
            item = None
        elif prefix == "GS":
            document.gs = line
            block = None
            party = None
            item = None
        elif prefix == "GE":
            close_item()
            document.ge = line
            block = None
            party = None
        elif prefix == "IEA":
            close_item()
            document.iea = line
            block = None
            party = None
        elif prefix == "ST":
            document.st = line
            block = None
            party = None
        elif prefix == "BPT":
            document.bpt = line
        elif prefix == "CTT":
            close_item()
            attach_party()
            document.ctt = line
            block = None
        elif prefix == "SE":
            close_item()
            document.se = line
            block = None
            party = None
        elif prefix == "PTD":
            start_ptd(line)
        elif prefix == "N1":
            start_party(line)
        elif prefix == "N3":
            close_item()
            if party is not None:
                party.n3 = line
            elif block is not None:
                block.extra.append(line)
            else:
                document.header_other.append(line)
        elif prefix == "N4":
            close_item()
            if party is not None:
                party.n4 = line
            elif block is not None:
                block.extra.append(line)
            else:
                document.header_other.append(line)
        elif prefix == "QTY":
            start_item(line)
        elif prefix == "LIN" and item is not None:
            item.lin = line
        elif prefix == "UIT" and item is not None:
            item.uit = line
        elif prefix == "PID" and item is not None:
            item.pid = line
        elif prefix == "DTM":
            if item is not None:
                item.dtm.append(line)
            elif block is None:
                document.header_dtm.append(line)
            else:
                close_item()
                block.extra.append(line)
        elif block is not None:
            if item is not None:
                item.extra.append(line)
            elif party is not None:
                party.extra.append(line)
            else:
                block.extra.append(line)
        elif prefix in {"ISA", "GS"}:
            continue
        else:
            document.header_other.append(line)

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


def _compare_party(gdl: PosParty, legacy: PosParty) -> list[ReportRow]:
    rows: list[ReportRow] = []
    rows.extend(_compare_optional(gdl.n1, legacy.n1))
    rows.extend(_compare_optional(gdl.n3, legacy.n3))
    rows.extend(_compare_optional(gdl.n4, legacy.n4))
    rows.extend(_compare_lists(gdl.extra, legacy.extra))
    return rows


def _emit_party_missing(party: PosParty, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(party.n1)
    add(party.n3)
    add(party.n4)
    for extra in party.extra:
        add(extra)
    return rows


def _emit_item_missing(item: PosItem, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(item.qty)
    add(item.lin)
    add(item.uit)
    add(item.pid)
    for line in item.dtm:
        add(line)
    for extra in item.extra:
        add(extra)
    return rows


def _emit_ptd_missing(block: PtdBlock, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(block.ptd)
    rows.extend(_emit_party_missing(block.ship_to, side))
    rows.extend(_emit_party_missing(block.bill_to, side))
    for extra in block.extra:
        add(extra)
    for item in block.items:
        rows.extend(_emit_item_missing(item, side))
    return rows


def _compare_items(gdl_items: list[PosItem], legacy_items: list[PosItem]) -> list[ReportRow]:
    """Match QTY/LIN groups inside one PTD. Order may differ."""
    rows: list[ReportRow] = []
    used = [False] * len(legacy_items)
    for gdl_item in gdl_items:
        found = None
        for index, legacy_item in enumerate(legacy_items):
            if used[index]:
                continue
            if gdl_item.lin and gdl_item.lin == legacy_item.lin:
                found = index
                break
        if found is None:
            rows.extend(_emit_item_missing(gdl_item, "gdl"))
            continue
        used[found] = True
        legacy_item = legacy_items[found]
        rows.extend(_compare_optional(gdl_item.qty, legacy_item.qty))
        rows.extend(_compare_optional(gdl_item.lin, legacy_item.lin))
        rows.extend(_compare_optional(gdl_item.uit, legacy_item.uit))
        rows.extend(_compare_optional(gdl_item.pid, legacy_item.pid))
        rows.extend(_compare_lists(gdl_item.dtm, legacy_item.dtm))
        rows.extend(_compare_lists(gdl_item.extra, legacy_item.extra))
    for index, legacy_item in enumerate(legacy_items):
        if not used[index]:
            rows.extend(_emit_item_missing(legacy_item, "legacy"))
    return rows


def _compare_ptd(gdl_block: PtdBlock, legacy_block: PtdBlock) -> list[ReportRow]:
    rows: list[ReportRow] = []
    rows.extend(_compare_optional(gdl_block.ptd, legacy_block.ptd))
    rows.extend(_compare_party(gdl_block.ship_to, legacy_block.ship_to))
    rows.extend(_compare_party(gdl_block.bill_to, legacy_block.bill_to))
    rows.extend(_compare_lists(gdl_block.extra, legacy_block.extra))
    rows.extend(_compare_items(gdl_block.items, legacy_block.items))
    return rows


def _document_line_count(document: PosDocument) -> int:
    count = sum(
        1
        for value in (
            document.isa,
            document.gs,
            document.st,
            document.bpt,
            document.ctt,
            document.se,
            document.ge,
            document.iea,
            document.distributor.n1,
            document.distributor.n3,
            document.distributor.n4,
        )
        if value
    )
    count += len(document.header_dtm) + len(document.header_other) + len(document.other)
    count += len(document.distributor.extra)
    for block in document.ptd_blocks:
        count += 1 if block.ptd else 0
        for party in (block.ship_to, block.bill_to):
            count += sum(1 for value in (party.n1, party.n3, party.n4) if value)
            count += len(party.extra)
        count += len(block.extra)
        for item in block.items:
            count += sum(1 for value in (item.qty, item.lin, item.uit, item.pid) if value)
            count += len(item.dtm) + len(item.extra)
    return count


def compare_pos_867(gdl_lines: Iterable[str], legacy_lines: Iterable[str]) -> ComparisonResult:
    """Compare two 867 POS files: envelope, header, then PTD loops by ship-to N1."""
    gdl_doc = parse_pos_document(list(gdl_lines))
    legacy_doc = parse_pos_document(list(legacy_lines))
    rows: list[ReportRow] = []

    rows.extend(_compare_optional(gdl_doc.isa, legacy_doc.isa))
    rows.extend(_compare_optional(gdl_doc.gs, legacy_doc.gs))
    rows.extend(_compare_optional(gdl_doc.st, legacy_doc.st))
    rows.extend(_compare_optional(gdl_doc.bpt, legacy_doc.bpt))
    rows.extend(_compare_lists(gdl_doc.header_dtm, legacy_doc.header_dtm))
    rows.extend(_compare_party(gdl_doc.distributor, legacy_doc.distributor))
    rows.extend(_compare_lists(gdl_doc.header_other, legacy_doc.header_other))
    rows.extend(_compare_lists(gdl_doc.other, legacy_doc.other))

    leftover_legacy: dict[str, list[int]] = {}
    for index, block in enumerate(legacy_doc.ptd_blocks):
        if block.match_key:
            leftover_legacy.setdefault(block.match_key, []).append(index)
    used_legacy: set[int] = set()
    paired_blocks = 0

    for gdl_block in gdl_doc.ptd_blocks:
        pair_index = None
        if gdl_block.match_key:
            candidates = leftover_legacy.get(gdl_block.match_key) or []
            if candidates:
                pair_index = candidates.pop(0)
        if pair_index is None:
            rows.extend(_emit_ptd_missing(gdl_block, "gdl"))
            continue
        used_legacy.add(pair_index)
        paired_blocks += 1
        rows.extend(_compare_ptd(gdl_block, legacy_doc.ptd_blocks[pair_index]))

    for index, legacy_block in enumerate(legacy_doc.ptd_blocks):
        if index not in used_legacy:
            rows.extend(_emit_ptd_missing(legacy_block, "legacy"))

    rows.extend(_compare_optional(gdl_doc.ctt, legacy_doc.ctt))
    rows.extend(_compare_optional(gdl_doc.se, legacy_doc.se))
    rows.extend(_compare_optional(gdl_doc.ge, legacy_doc.ge))
    rows.extend(_compare_optional(gdl_doc.iea, legacy_doc.iea))

    gdl_items = sum(len(block.items) for block in gdl_doc.ptd_blocks)
    legacy_items = sum(len(block.items) for block in legacy_doc.ptd_blocks)
    return ComparisonResult(
        rows=rows,
        gdl_line_count=_document_line_count(gdl_doc),
        legacy_line_count=_document_line_count(legacy_doc),
        gdl_block_count=len(gdl_doc.ptd_blocks),
        legacy_block_count=len(legacy_doc.ptd_blocks),
        paired_block_count=paired_blocks,
    )


# Alias used in summary metrics: PTD count is the block count; items are inside.
compare_x12_867 = compare_pos_867
