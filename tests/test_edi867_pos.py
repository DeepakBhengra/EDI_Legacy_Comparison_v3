from __future__ import annotations

from pathlib import Path

from edi846_compare import (
    FILL_ORANGE,
    FILL_RED,
    STATUS_MATCH,
    STATUS_MISSING_IN_GDL,
    STATUS_MISSING_IN_IMPULSE,
    STATUS_MISMATCH,
    compare_loaded_segments,
)
from edi867_compare import compare_pos_867, parse_pos_document
from x12_format import detect_x12_transaction, load_local_segments


def _header() -> list[str]:
    return [
        "ISA*00*          *00*          *01*004919486MX    *ZZ*SEM950215S98   *261016*2331*U*00401*000005625*0*P*>~",
        "GS*PT*004919486MX*SEM950215S98*20261016*2331*971*X*004010~",
        "ST*867*0001~",
        "BPT*00*261016232504*20261016*02~",
        "DTM*091*20261016~",
        "N1*DS*INGRAM MICRO MEXICO*1*10~",
        "N3*LAGUNA DE TERMINOS NO.249~",
        "N4*MEXICO D.F.**11320*MX*WH*00~",
    ]


def _ptd(ship_name: str, account: str, sku: str, qty: str, part: str = "0B93621") -> list[str]:
    return [
        "PTD*SD~",
        f"N1*ST*{ship_name}*91*{account}~",
        "N3*STREET 1~",
        "N4*CITY*CX*01000*MX~",
        f"N1*BT*{ship_name}~",
        "N3*STREET 1~",
        "N4*CITY*CX*01000*MX~",
        f"QTY*39*{qty}~",
        f"LIN**VP*{part}*MG*{sku}~",
        "UIT*EA*100~",
        f"PID*X****{sku} DESC~",
        "DTM*003*20261014~",
        "DTM*011*20261014~",
    ]


def _trailer() -> list[str]:
    return ["CTT*1*1~", "SE*20*0001~", "GE*1*971~", "IEA*1*000005625~"]


def rows_as_tuples(result) -> list[tuple[str, str, str]]:
    return [(row.gdl_segment, row.legacy_segment, row.status) for row in result.rows]


def test_detect_x12_transaction_867_and_846() -> None:
    assert detect_x12_transaction(_header()) == "867"
    assert detect_x12_transaction(["ISA*A", "GS*IB*A", "ST*846*0001"]) == "846"
    assert detect_x12_transaction(["GS*PT*A*B"]) == "867"


def test_parse_pos_reads_ptd_parties_and_items() -> None:
    document = parse_pos_document(_header() + _ptd("ACME", "1001", "SKU-A", "4") + _trailer())
    assert document.st == "ST*867*0001~"
    assert document.distributor.n1 and document.distributor.n1.startswith("N1*DS*")
    assert len(document.ptd_blocks) == 1
    block = document.ptd_blocks[0]
    assert block.ship_to.n1 == "N1*ST*ACME*91*1001~"
    assert block.bill_to.n1 == "N1*BT*ACME~"
    assert block.items[0].qty == "QTY*39*4~"
    assert block.items[0].lin == "LIN**VP*0B93621*MG*SKU-A~"
    assert [line[:7] for line in block.items[0].dtm] == ["DTM*003", "DTM*011"]


def test_ptd_order_does_not_matter() -> None:
    gdl = (
        _header()
        + _ptd("BETA", "2002", "SKU-B", "2", "0B2")
        + _ptd("ALPHA", "1001", "SKU-A", "1", "0B1")
        + _trailer()
    )
    legacy = (
        _header()
        + _ptd("ALPHA", "1001", "SKU-A", "1", "0B1")
        + _ptd("BETA", "2002", "SKU-B", "2", "0B2")
        + _trailer()
    )
    result = compare_pos_867(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("N1*ST*ALPHA*91*1001~", "N1*ST*ALPHA*91*1001~", STATUS_MATCH) in tuples
    assert ("N1*ST*BETA*91*2002~", "N1*ST*BETA*91*2002~", STATUS_MATCH) in tuples
    assert ("LIN**VP*0B1*MG*SKU-A~", "LIN**VP*0B1*MG*SKU-A~", STATUS_MATCH) in tuples
    assert result.missing_in_impulse == 0
    assert result.missing_in_gdl == 0
    assert result.paired_block_count == 2


def test_lin_order_inside_ptd_does_not_matter() -> None:
    def two_items(first: tuple[str, str], second: tuple[str, str]) -> list[str]:
        sku_a, qty_a = first
        sku_b, qty_b = second
        return (
            _header()
            + [
                "PTD*SD~",
                "N1*ST*ACME*91*1001~",
                "N3*STREET 1~",
                "N4*CITY*CX*01000*MX~",
                "N1*BT*ACME~",
                "N3*STREET 1~",
                "N4*CITY*CX*01000*MX~",
                f"QTY*39*{qty_a}~",
                f"LIN**VP*{sku_a}*MG*{sku_a}~",
                "UIT*EA*100~",
                f"PID*X****{sku_a}~",
                "DTM*003*20261014~",
                "DTM*011*20261014~",
                f"QTY*39*{qty_b}~",
                f"LIN**VP*{sku_b}*MG*{sku_b}~",
                "UIT*EA*100~",
                f"PID*X****{sku_b}~",
                "DTM*003*20261014~",
                "DTM*011*20261014~",
            ]
            + _trailer()
        )

    result = compare_pos_867(
        two_items(("BBB", "2"), ("AAA", "1")),
        two_items(("AAA", "1"), ("BBB", "2")),
    )
    tuples = rows_as_tuples(result)
    assert ("LIN**VP*BBB*MG*BBB~", "LIN**VP*BBB*MG*BBB~", STATUS_MATCH) in tuples
    assert ("LIN**VP*AAA*MG*AAA~", "LIN**VP*AAA*MG*AAA~", STATUS_MATCH) in tuples
    assert ("QTY*39*1~", "QTY*39*1~", STATUS_MATCH) in tuples
    assert result.missing_in_impulse == 0
    assert result.mismatches == 0


def test_qty_difference_is_mismatch() -> None:
    gdl = _header() + _ptd("ACME", "1001", "SKU-A", "4") + _trailer()
    legacy = _header() + _ptd("ACME", "1001", "SKU-A", "9") + _trailer()
    result = compare_pos_867(gdl, legacy)
    assert ("QTY*39*4~", "QTY*39*9~", STATUS_MISMATCH) in rows_as_tuples(result)
    orange = [row for row in result.rows if row.status == STATUS_MISMATCH]
    assert orange[0].fill == FILL_ORANGE


def test_missing_ptd_is_missing_in_impulse() -> None:
    gdl = (
        _header()
        + _ptd("ONLYGDL", "9999", "SKU-X", "1")
        + _ptd("SHARED", "1001", "SKU-A", "1")
        + _trailer()
    )
    legacy = _header() + _ptd("SHARED", "1001", "SKU-A", "1") + _trailer()
    result = compare_pos_867(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("N1*ST*ONLYGDL*91*9999~", "", STATUS_MISSING_IN_IMPULSE) in tuples
    assert ("QTY*39*1~", "", STATUS_MISSING_IN_IMPULSE) in tuples
    assert any(row.fill == FILL_RED for row in result.rows if row.status == STATUS_MISSING_IN_IMPULSE)


def test_same_sku_different_ship_to_does_not_pair() -> None:
    gdl = _header() + _ptd("WH1", "1001", "SKU-A", "1") + _trailer()
    legacy = _header() + _ptd("WH2", "2002", "SKU-A", "1") + _trailer()
    result = compare_pos_867(gdl, legacy)
    tuples = rows_as_tuples(result)
    assert ("N1*ST*WH1*91*1001~", "", STATUS_MISSING_IN_IMPULSE) in tuples
    assert ("", "N1*ST*WH2*91*2002~", STATUS_MISSING_IN_GDL) in tuples
    assert result.paired_block_count == 0


def test_bpt_mismatch_is_orange() -> None:
    gdl = _header() + _trailer()
    legacy = list(_header())
    legacy[3] = "BPT*00*LEGACYREF*20261016*02~"
    legacy += _trailer()
    result = compare_pos_867(gdl, legacy)
    assert (
        "BPT*00*261016232504*20261016*02~",
        "BPT*00*LEGACYREF*20261016*02~",
        STATUS_MISMATCH,
    ) in rows_as_tuples(result)


def test_compare_loaded_segments_dispatches_867() -> None:
    body = _header() + _ptd("ACME", "1001", "SKU-A", "1") + _trailer()
    result = compare_loaded_segments(body, body)
    assert result.matches > 0
    assert result.mismatches == 0
    assert result.paired_block_count == 1


def test_compare_loaded_segments_rejects_846_vs_867() -> None:
    result = compare_loaded_segments(
        ["ISA*A", "GS*IB*A", "ST*846*0001"],
        _header()[:3],
    )
    assert result.rows[0].status == STATUS_MISMATCH
    assert "846" in result.rows[0].gdl_segment
    assert "867" in result.rows[0].legacy_segment


def test_sample_pos_file_self_compares() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "POS_x12_1015.txt"
    segments = load_local_segments(path)
    document = parse_pos_document(segments)
    result = compare_pos_867(segments, segments)
    assert detect_x12_transaction(segments) == "867"
    assert len(document.ptd_blocks) == 104
    assert sum(len(block.items) for block in document.ptd_blocks) == 158
    assert result.mismatches == 0
    assert result.missing_in_impulse == 0
    assert result.paired_block_count == 104
    assert result.gdl_line_count == len(segments)
