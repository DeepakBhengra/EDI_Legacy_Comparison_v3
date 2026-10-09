#!/usr/bin/env python3
"""Compare GDL and Legacy EDIFACT INVRPT (EDI 846) segment lists.

Mirrors the X12 846 rules: interchange envelope once, message header by
qualifier, then line items matched by location + product id so LIN order may
differ. QTY rows are paired with their RFF inside the item.
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
from edifact_format import edifact_element, edifact_qualifier, edifact_tag


@dataclass
class QtyGroup:
    rff: str | None = None
    qty: str | None = None
    extra: list[str] = field(default_factory=list)


@dataclass
class InvLine:
    lin: str | None = None
    loc: str | None = None
    pia: list[str] = field(default_factory=list)
    imd: list[str] = field(default_factory=list)
    dtm: list[str] = field(default_factory=list)
    qty_groups: list[QtyGroup] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    @property
    def product_id(self) -> str:
        if not self.lin:
            return ""
        return edifact_element(self.lin, 2)

    @property
    def location_id(self) -> str:
        if not self.loc:
            return ""
        return edifact_element(self.loc, 1)

    @property
    def match_key(self) -> str:
        return f"{self.location_id}|{self.product_id}"


@dataclass
class InvMessage:
    unh: str | None = None
    bgm: str | None = None
    dtm: list[str] = field(default_factory=list)
    nad: list[str] = field(default_factory=list)
    cux: str | None = None
    other_header: list[str] = field(default_factory=list)
    items: list[InvLine] = field(default_factory=list)
    uns: str | None = None
    unt: str | None = None
    other: list[str] = field(default_factory=list)


@dataclass
class InvDocument:
    una: str | None = None
    unb: str | None = None
    messages: list[InvMessage] = field(default_factory=list)
    unz: str | None = None
    other: list[str] = field(default_factory=list)


def parse_edifact_invrpt(lines: Iterable[str]) -> InvDocument:
    """Split an INVRPT dump into UNB/UNZ, UNH-UNT, and LIN item loops."""
    document = InvDocument()
    message: InvMessage | None = None
    item: InvLine | None = None
    pending_group: QtyGroup | None = None

    def close_group() -> None:
        nonlocal pending_group
        if item is not None and pending_group is not None:
            item.qty_groups.append(pending_group)
        pending_group = None

    def start_item(lin_line: str) -> None:
        nonlocal item, pending_group
        close_group()
        if message is None:
            return
        item = InvLine(lin=lin_line)
        message.items.append(item)
        pending_group = None

    def start_message(unh_line: str) -> None:
        nonlocal message, item, pending_group
        close_group()
        message = InvMessage(unh=unh_line)
        document.messages.append(message)
        item = None
        pending_group = None

    for line in lines:
        if not line:
            continue
        tag = edifact_tag(line)
        if tag == "UNA":
            document.una = line
            message = None
            item = None
        elif tag == "UNB":
            document.unb = line
            message = None
            item = None
        elif tag == "UNZ":
            close_group()
            document.unz = line
            message = None
            item = None
        elif tag == "UNH":
            start_message(line)
        elif message is None:
            document.other.append(line)
        elif tag == "BGM" and item is None:
            message.bgm = line
        elif tag == "NAD" and item is None:
            message.nad.append(line)
        elif tag == "CUX" and item is None:
            message.cux = line
        elif tag == "DTM" and item is None:
            message.dtm.append(line)
        elif tag == "LIN":
            start_item(line)
        elif tag == "UNS":
            close_group()
            item = None
            message.uns = line
        elif tag == "UNT":
            close_group()
            item = None
            message.unt = line
        elif item is None:
            message.other_header.append(line)
        elif tag == "LOC":
            close_group()
            item.loc = line
        elif tag == "PIA":
            close_group()
            item.pia.append(line)
        elif tag == "IMD":
            close_group()
            item.imd.append(line)
        elif tag == "DTM":
            close_group()
            item.dtm.append(line)
        elif tag == "RFF":
            close_group()
            pending_group = QtyGroup(rff=line)
        elif tag == "QTY":
            if pending_group is not None:
                pending_group.qty = line
                close_group()
            else:
                item.qty_groups.append(QtyGroup(qty=line))
        else:
            if pending_group is not None:
                pending_group.extra.append(line)
            else:
                item.other.append(line)

    close_group()
    return document


def _row(gdl: str, legacy: str, status: str) -> ReportRow:
    fill = None
    if status == STATUS_MISMATCH:
        fill = FILL_ORANGE
    elif status in {STATUS_MISSING_IN_IMPULSE, STATUS_MISSING_IN_GDL}:
        fill = FILL_RED
    return ReportRow(gdl_segment=gdl, legacy_segment=legacy, status=status, fill=fill)


def _lin_without_line_number(line: str) -> str:
    """Drop LIN line number so GDL LIN+2++SKU pairs with Legacy LIN+1++SKU."""
    parts = line.split("+")
    if len(parts) < 2:
        return line
    return "+".join([parts[0]] + parts[2:])


def _compare_optional(gdl: str | None, legacy: str | None) -> list[ReportRow]:
    if gdl is None and legacy is None:
        return []
    if gdl is not None and legacy is not None:
        status = STATUS_MATCH if gdl == legacy else STATUS_MISMATCH
        return [_row(gdl, legacy, status)]
    if gdl is not None:
        return [_row(gdl, "", STATUS_MISSING_IN_IMPULSE)]
    return [_row("", legacy or "", STATUS_MISSING_IN_GDL)]


def _compare_lin(gdl: str | None, legacy: str | None) -> list[ReportRow]:
    """Match LIN by product id; line numbers may differ after order-independent pairing."""
    if gdl is None and legacy is None:
        return []
    if gdl is not None and legacy is not None:
        same_product = _lin_without_line_number(gdl) == _lin_without_line_number(legacy)
        status = STATUS_MATCH if gdl == legacy or same_product else STATUS_MISMATCH
        return [_row(gdl, legacy, status)]
    return _compare_optional(gdl, legacy)


def _compare_lists(gdl_values: list[str], legacy_values: list[str]) -> list[ReportRow]:
    rows: list[ReportRow] = []
    limit = max(len(gdl_values), len(legacy_values))
    for index in range(limit):
        gdl = gdl_values[index] if index < len(gdl_values) else None
        legacy = legacy_values[index] if index < len(legacy_values) else None
        rows.extend(_compare_optional(gdl, legacy))
    return rows


def _compare_by_qualifier(gdl_values: list[str], legacy_values: list[str]) -> list[ReportRow]:
    """Match header NAD/DTM rows by qualifier; leftover rows are missing."""
    rows: list[ReportRow] = []
    used = [False] * len(legacy_values)
    for gdl in gdl_values:
        found = None
        gdl_q = edifact_qualifier(gdl)
        for index, legacy in enumerate(legacy_values):
            if used[index]:
                continue
            if edifact_qualifier(legacy) == gdl_q:
                found = index
                break
        if found is None:
            rows.append(_row(gdl, "", STATUS_MISSING_IN_IMPULSE))
            continue
        used[found] = True
        rows.extend(_compare_optional(gdl, legacy_values[found]))
    for index, legacy in enumerate(legacy_values):
        if not used[index]:
            rows.append(_row("", legacy, STATUS_MISSING_IN_GDL))
    return rows


def _qty_key(group: QtyGroup) -> str:
    rff_q = edifact_qualifier(group.rff) if group.rff else ""
    qty_q = edifact_qualifier(group.qty) if group.qty else ""
    return f"{rff_q}|{qty_q}|{group.rff or ''}"


def _compare_qty_groups(gdl_groups: list[QtyGroup], legacy_groups: list[QtyGroup]) -> list[ReportRow]:
    rows: list[ReportRow] = []
    used = [False] * len(legacy_groups)
    for gdl_group in gdl_groups:
        found = None
        key = _qty_key(gdl_group)
        for index, legacy_group in enumerate(legacy_groups):
            if used[index]:
                continue
            if _qty_key(legacy_group) == key or (
                gdl_group.rff
                and legacy_group.rff
                and gdl_group.rff == legacy_group.rff
            ):
                found = index
                break
            if (
                not gdl_group.rff
                and not legacy_group.rff
                and edifact_qualifier(gdl_group.qty or "")
                == edifact_qualifier(legacy_group.qty or "")
            ):
                found = index
                break
        if found is None:
            if gdl_group.rff:
                rows.append(_row(gdl_group.rff, "", STATUS_MISSING_IN_IMPULSE))
            if gdl_group.qty:
                rows.append(_row(gdl_group.qty, "", STATUS_MISSING_IN_IMPULSE))
            for extra in gdl_group.extra:
                rows.append(_row(extra, "", STATUS_MISSING_IN_IMPULSE))
            continue
        used[found] = True
        legacy_group = legacy_groups[found]
        rows.extend(_compare_optional(gdl_group.rff, legacy_group.rff))
        rows.extend(_compare_optional(gdl_group.qty, legacy_group.qty))
        rows.extend(_compare_lists(gdl_group.extra, legacy_group.extra))
    for index, legacy_group in enumerate(legacy_groups):
        if used[index]:
            continue
        if legacy_group.rff:
            rows.append(_row("", legacy_group.rff, STATUS_MISSING_IN_GDL))
        if legacy_group.qty:
            rows.append(_row("", legacy_group.qty, STATUS_MISSING_IN_GDL))
        for extra in legacy_group.extra:
            rows.append(_row("", extra, STATUS_MISSING_IN_GDL))
    return rows


def _emit_item_missing(item: InvLine, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(item.lin)
    add(item.loc)
    for line in item.pia:
        add(line)
    for line in item.imd:
        add(line)
    for line in item.dtm:
        add(line)
    for extra in item.other:
        add(extra)
    for group in item.qty_groups:
        add(group.rff)
        add(group.qty)
        for extra in group.extra:
            add(extra)
    return rows


def _compare_items(gdl_items: list[InvLine], legacy_items: list[InvLine]) -> list[ReportRow]:
    """Match LIN loops by location + product id. Order may differ."""
    rows: list[ReportRow] = []
    used = [False] * len(legacy_items)
    for gdl_item in gdl_items:
        found = None
        for index, legacy_item in enumerate(legacy_items):
            if used[index]:
                continue
            if gdl_item.product_id and gdl_item.match_key == legacy_item.match_key:
                found = index
                break
        if found is None:
            rows.extend(_emit_item_missing(gdl_item, "gdl"))
            continue
        used[found] = True
        legacy_item = legacy_items[found]
        rows.extend(_compare_lin(gdl_item.lin, legacy_item.lin))
        rows.extend(_compare_optional(gdl_item.loc, legacy_item.loc))
        rows.extend(_compare_lists(gdl_item.pia, legacy_item.pia))
        rows.extend(_compare_lists(gdl_item.imd, legacy_item.imd))
        rows.extend(_compare_lists(gdl_item.dtm, legacy_item.dtm))
        rows.extend(_compare_lists(gdl_item.other, legacy_item.other))
        rows.extend(_compare_qty_groups(gdl_item.qty_groups, legacy_item.qty_groups))
    for index, legacy_item in enumerate(legacy_items):
        if not used[index]:
            rows.extend(_emit_item_missing(legacy_item, "legacy"))
    return rows


def _emit_message_missing(message: InvMessage, side: str) -> list[ReportRow]:
    status = STATUS_MISSING_IN_IMPULSE if side == "gdl" else STATUS_MISSING_IN_GDL
    rows: list[ReportRow] = []

    def add(value: str | None) -> None:
        if not value:
            return
        if side == "gdl":
            rows.append(_row(value, "", status))
        else:
            rows.append(_row("", value, status))

    add(message.unh)
    add(message.bgm)
    for line in message.dtm:
        add(line)
    for line in message.nad:
        add(line)
    add(message.cux)
    for line in message.other_header:
        add(line)
    for item in message.items:
        rows.extend(_emit_item_missing(item, side))
    add(message.uns)
    add(message.unt)
    for line in message.other:
        add(line)
    return rows


def _compare_messages(gdl_msg: InvMessage, legacy_msg: InvMessage) -> list[ReportRow]:
    rows: list[ReportRow] = []
    rows.extend(_compare_optional(gdl_msg.unh, legacy_msg.unh))
    rows.extend(_compare_optional(gdl_msg.bgm, legacy_msg.bgm))
    rows.extend(_compare_by_qualifier(gdl_msg.dtm, legacy_msg.dtm))
    rows.extend(_compare_by_qualifier(gdl_msg.nad, legacy_msg.nad))
    rows.extend(_compare_optional(gdl_msg.cux, legacy_msg.cux))
    rows.extend(_compare_lists(gdl_msg.other_header, legacy_msg.other_header))
    rows.extend(_compare_items(gdl_msg.items, legacy_msg.items))
    rows.extend(_compare_optional(gdl_msg.uns, legacy_msg.uns))
    rows.extend(_compare_optional(gdl_msg.unt, legacy_msg.unt))
    rows.extend(_compare_lists(gdl_msg.other, legacy_msg.other))
    return rows


def _document_line_count(document: InvDocument) -> int:
    count = sum(1 for value in (document.una, document.unb, document.unz) if value)
    count += len(document.other)
    for message in document.messages:
        count += sum(1 for value in (message.unh, message.bgm, message.cux, message.uns, message.unt) if value)
        count += len(message.dtm) + len(message.nad) + len(message.other_header) + len(message.other)
        for item in message.items:
            count += 1 if item.lin else 0
            count += 1 if item.loc else 0
            count += len(item.pia) + len(item.imd) + len(item.dtm) + len(item.other)
            for group in item.qty_groups:
                count += 1 if group.rff else 0
                count += 1 if group.qty else 0
                count += len(group.extra)
    return count


def compare_edifact_invrpt(gdl_lines: Iterable[str], legacy_lines: Iterable[str]) -> ComparisonResult:
    """Compare two INVRPT files: UNB/UNZ, header, then LIN items by location+SKU."""
    gdl_doc = parse_edifact_invrpt(list(gdl_lines))
    legacy_doc = parse_edifact_invrpt(list(legacy_lines))
    rows: list[ReportRow] = []

    rows.extend(_compare_optional(gdl_doc.una, legacy_doc.una))
    rows.extend(_compare_optional(gdl_doc.unb, legacy_doc.unb))
    rows.extend(_compare_lists(gdl_doc.other, legacy_doc.other))

    limit = max(len(gdl_doc.messages), len(legacy_doc.messages))
    for index in range(limit):
        gdl_msg = gdl_doc.messages[index] if index < len(gdl_doc.messages) else None
        legacy_msg = legacy_doc.messages[index] if index < len(legacy_doc.messages) else None
        if gdl_msg is not None and legacy_msg is not None:
            rows.extend(_compare_messages(gdl_msg, legacy_msg))
        elif gdl_msg is not None:
            rows.extend(_emit_message_missing(gdl_msg, "gdl"))
        elif legacy_msg is not None:
            rows.extend(_emit_message_missing(legacy_msg, "legacy"))

    rows.extend(_compare_optional(gdl_doc.unz, legacy_doc.unz))

    gdl_items = sum(len(message.items) for message in gdl_doc.messages)
    legacy_items = sum(len(message.items) for message in legacy_doc.messages)
    paired_items = 0
    for index in range(min(len(gdl_doc.messages), len(legacy_doc.messages))):
        used = [False] * len(legacy_doc.messages[index].items)
        for gdl_item in gdl_doc.messages[index].items:
            for item_index, legacy_item in enumerate(legacy_doc.messages[index].items):
                if used[item_index]:
                    continue
                if gdl_item.product_id and gdl_item.match_key == legacy_item.match_key:
                    used[item_index] = True
                    paired_items += 1
                    break
    return ComparisonResult(
        rows=rows,
        gdl_line_count=_document_line_count(gdl_doc),
        legacy_line_count=_document_line_count(legacy_doc),
        gdl_block_count=gdl_items,
        legacy_block_count=legacy_items,
        paired_block_count=paired_items,
    )
