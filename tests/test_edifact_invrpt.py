from __future__ import annotations

from pathlib import Path

from edi846_compare import (
    FILL_ORANGE,
    STATUS_MATCH,
    STATUS_MISSING_IN_GDL,
    STATUS_MISSING_IN_IMPULSE,
    STATUS_MISMATCH,
    compare_loaded_segments,
)
from edifact_format import parse_edifact_segments
from edifact_invrpt_compare import compare_edifact_invrpt, parse_edifact_invrpt
from x12_format import load_local_segments


def _header() -> list[str]:
    return [
        "UNB+UNOA:2+INGRAMMICROSG:ZZ+098533326TST:ZZ+260911:0234+39++INVRPT",
        "UNH+1+INVRPT:D:97A:UN",
        "BGM+35::6+20260911023420.442+9",
        "DTM+91:20260909:102",
        "NAD+DS+936142999999::90",
        "NAD+MF+SEAGATE::90",
    ]


def _item(line_no: str, sku: str, loc: str, qty_on_hand: str) -> list[str]:
    return [
        f"LIN+{line_no}++{sku}:MF",
        f"LOC+14+{loc}",
        "RFF+AEN:1",
        f"QTY+17:{qty_on_hand}:EA",
        "RFF+AEN:2",
        "QTY+16:0:EA",
    ]


def _trailer() -> list[str]:
    return ["UNT+20+1", "UNZ+1+39"]


def rows_as_tuples(result) -> list[tuple[str, str, str]]:
    return [(row.gdl_segment, row.legacy_segment, row.status) for row in result.rows]


def test_parse_edifact_segments_splits_apostrophe_terminator() -> None:
    raw = (
        "UNA:+.? '"
        "UNB+UNOA:2+GDL:ZZ+LEG:ZZ+260911:0234+1++INVRPT'"
        "UNH+1+INVRPT:D:97A:UN'"
        "LIN+1++STFR5000800:MF'"
        "UNT+4+1'"
        "UNZ+1+1'"
    )
    segments = parse_edifact_segments(raw)
    assert segments[0].startswith("UNB+")
    assert "LIN+1++STFR5000800:MF" in segments
    assert segments[-1].startswith("UNZ+")


def test_parse_invrpt_reads_lin_loc_and_qty_groups() -> None:
    document = parse_edifact_invrpt(_header() + _item("1", "STFR5000800", "2030SG01", "2") + _trailer())
    assert document.unb and document.unb.startswith("UNB+")
    assert len(document.messages) == 1
    item = document.messages[0].items[0]
    assert item.product_id == "STFR5000800:MF"
    assert item.location_id == "2030SG01"
    assert item.qty_groups[0].qty == "QTY+17:2:EA"
    assert document.unz == "UNZ+1+39"


def test_edifact_lin_order_does_not_matter() -> None:
    gdl = (
        _header()
        + _item("1", "BBB", "2030SG01", "2")
        + _item("2", "AAA", "2030SG01", "1")
        + _trailer()
    )
    legacy = (
        _header()
        + _item("1", "AAA", "2030SG01", "1")
        + _item("2", "BBB", "2030SG01", "2")
        + _trailer()
    )
    result = compare_edifact_invrpt(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("LIN+2++AAA:MF", "LIN+1++AAA:MF", STATUS_MATCH) in tuples
    assert ("LIN+1++BBB:MF", "LIN+2++BBB:MF", STATUS_MATCH) in tuples
    assert ("QTY+17:1:EA", "QTY+17:1:EA", STATUS_MATCH) in tuples
    assert ("QTY+17:2:EA", "QTY+17:2:EA", STATUS_MATCH) in tuples
    assert result.missing_in_impulse == 0
    assert result.missing_in_gdl == 0
    assert result.mismatches == 0
    assert result.paired_block_count == 2


def test_edifact_qty_difference_is_mismatch() -> None:
    gdl = _header() + _item("1", "AAA", "2030SG01", "2") + _trailer()
    legacy = _header() + _item("1", "AAA", "2030SG01", "9") + _trailer()
    result = compare_edifact_invrpt(gdl, legacy)
    assert (
        "QTY+17:2:EA",
        "QTY+17:9:EA",
        STATUS_MISMATCH,
    ) in rows_as_tuples(result)


def test_edifact_missing_lin_is_missing_in_impulse() -> None:
    gdl = (
        _header()
        + _item("1", "ONLYGDL", "2030SG01", "1")
        + _item("2", "SHARED", "2030SG01", "1")
        + _trailer()
    )
    legacy = _header() + _item("1", "SHARED", "2030SG01", "1") + _trailer()
    result = compare_edifact_invrpt(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("LIN+1++ONLYGDL:MF", "", STATUS_MISSING_IN_IMPULSE) in tuples
    assert ("QTY+17:1:EA", "", STATUS_MISSING_IN_IMPULSE) in tuples


def test_edifact_same_sku_different_location_does_not_pair() -> None:
    gdl = _header() + _item("1", "AAA", "WH1", "1") + _trailer()
    legacy = _header() + _item("1", "AAA", "WH2", "1") + _trailer()
    result = compare_edifact_invrpt(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("LIN+1++AAA:MF", "", STATUS_MISSING_IN_IMPULSE) in tuples
    assert ("", "LIN+1++AAA:MF", STATUS_MISSING_IN_GDL) in tuples


def test_edifact_nad_order_does_not_matter() -> None:
    gdl = [
        "UNB+UNOA:2+GDL",
        "UNH+1+INVRPT:D:97A:UN",
        "BGM+35::6+1+9",
        "DTM+91:20260909:102",
        "NAD+DS+WAREHOUSE::90",
        "NAD+MF+SEAGATE::90",
        "UNT+6+1",
        "UNZ+1+1",
    ]
    legacy = [
        "UNB+UNOA:2+GDL",
        "UNH+1+INVRPT:D:97A:UN",
        "BGM+35::6+1+9",
        "NAD+MF+SEAGATE::90",
        "NAD+DS+WAREHOUSE::90",
        "DTM+91:20260909:102",
        "UNT+6+1",
        "UNZ+1+1",
    ]
    result = compare_edifact_invrpt(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("NAD+DS+WAREHOUSE::90", "NAD+DS+WAREHOUSE::90", STATUS_MATCH) in tuples
    assert ("NAD+MF+SEAGATE::90", "NAD+MF+SEAGATE::90", STATUS_MATCH) in tuples
    assert result.mismatches == 0


def test_edifact_unb_mismatch_is_orange() -> None:
    gdl = ["UNB+GDL"] + _header()[1:] + _trailer()
    legacy = ["UNB+LEG"] + _header()[1:] + _trailer()
    result = compare_edifact_invrpt(gdl, legacy)
    assert ("UNB+GDL", "UNB+LEG", STATUS_MISMATCH) in rows_as_tuples(result)
    assert result.rows[0].fill == FILL_ORANGE


def test_compare_loaded_segments_dispatches_edifact() -> None:
    gdl = _header() + _item("1", "AAA", "2030SG01", "1") + _trailer()
    result = compare_loaded_segments(gdl, gdl)
    assert result.matches > 0
    assert result.mismatches == 0


def test_compare_loaded_segments_rejects_mixed_formats() -> None:
    result = compare_loaded_segments(["ISA~X12"], ["UNB+EDIFACT"])
    assert result.rows[0].status == STATUS_MISMATCH
    assert "X12" in result.rows[0].gdl_segment
    assert "EDIFACT" in result.rows[0].legacy_segment


def test_sample_invrpt_parses_all_line_items() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "EDIFACT_INVRPT_GDL.txt"
    segments = load_local_segments(path)
    document = parse_edifact_invrpt(segments)
    result = compare_edifact_invrpt(segments, segments)
    assert segments[0].startswith("UNB+")
    assert len(document.messages[0].items) == 79
    assert result.mismatches == 0
    assert result.paired_block_count == 79
    assert result.gdl_line_count == len(segments)
