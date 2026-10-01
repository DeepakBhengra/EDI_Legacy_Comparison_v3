from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from compare_segments import (
    FILL_ORANGE,
    FILL_RED,
    STATUS_MATCH,
    STATUS_MISMATCH,
    STATUS_MISSING_IN_GDL,
    STATUS_MISSING_IN_IMPULSE,
    compare_segments,
    parse_edi_document,
    read_segment_lines,
    timestamped_output_path,
    write_excel_report,
)


def rows_as_tuples(result) -> list[tuple[str, str, str, str | None]]:
    return [(row.gdl_segment, row.legacy_segment, row.status, row.fill) for row in result.rows]


def test_isa_and_gs_are_compared_side_by_side() -> None:
    result = compare_segments(
        ["ISA~GDL", "GS~GDL"],
        ["ISA~LEG", "GS~GDL"],
    )
    assert rows_as_tuples(result) == [
        ("ISA~GDL", "ISA~LEG", STATUS_MISMATCH, FILL_ORANGE),
        ("GS~GDL", "GS~GDL", STATUS_MATCH, None),
    ]


def test_lin_found_later_in_same_block_is_match() -> None:
    gdl = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "BIA~GDL",
        "N1~WH~WAREHOUSE~92~03",
        "PER~IC~EDITH",
        "LIN~~MG~BBB",
        "QTY~33~2~EA",
        "LIN~~MG~AAA",
        "QTY~33~1~EA",
        "CTT~2",
        "SE~10~0001",
    ]
    legacy = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "BIA~LEG",
        "N1~WH~WAREHOUSE~92~03",
        "PER~IC~EDITH",
        "LIN~~MG~AAA",
        "QTY~33~1~EA",
        "LIN~~MG~BBB",
        "QTY~33~2~EA",
        "CTT~2",
        "SE~10~0001",
    ]
    result = compare_segments(gdl, legacy)
    assert (
        "LIN~~MG~BBB",
        "LIN~~MG~BBB",
        STATUS_MATCH,
        None,
    ) in rows_as_tuples(result)
    assert (
        "LIN~~MG~AAA",
        "LIN~~MG~AAA",
        STATUS_MATCH,
        None,
    ) in rows_as_tuples(result)
    assert result.missing_in_impulse == 0
    assert result.missing_in_gdl == 0


def test_missing_lin_in_legacy_is_missing_in_impulse() -> None:
    gdl = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "LIN~~MG~ONLY-GDL",
        "QTY~33~1~EA",
        "CTT~1",
        "SE~6~0001",
    ]
    legacy = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "CTT~0",
        "SE~4~0001",
    ]
    result = compare_segments(gdl, legacy)
    assert (
        "LIN~~MG~ONLY-GDL",
        "",
        STATUS_MISSING_IN_IMPULSE,
        FILL_RED,
    ) in rows_as_tuples(result)
    assert (
        "QTY~33~1~EA",
        "",
        STATUS_MISSING_IN_IMPULSE,
        FILL_RED,
    ) in rows_as_tuples(result)


def test_extra_legacy_lin_is_missing_in_gdl() -> None:
    gdl = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "CTT~0",
        "SE~4~0001",
    ]
    legacy = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "LIN~~MG~ONLY-LEG",
        "QTY~33~9~EA",
        "CTT~1",
        "SE~6~0001",
    ]
    result = compare_segments(gdl, legacy)
    assert (
        "",
        "LIN~~MG~ONLY-LEG",
        STATUS_MISSING_IN_GDL,
        FILL_RED,
    ) in rows_as_tuples(result)
    assert (
        "",
        "QTY~33~9~EA",
        STATUS_MISSING_IN_GDL,
        FILL_RED,
    ) in rows_as_tuples(result)


def test_blocks_are_paired_by_n1_not_by_st_position() -> None:
    gdl = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~FIRST~92~03",
        "LIN~~MG~AAA",
        "QTY~33~1~EA",
        "CTT~1",
        "SE~6~0001",
        "ST~846~0002",
        "BIA~ORPHAN",
        "LIN~~MG~ORPHAN",
        "QTY~33~5~EA",
        "CTT~1",
        "SE~6~0002",
        "ST~846~0003",
        "N1~WH~SECOND~92~30",
        "LIN~~MG~BBB",
        "QTY~33~2~EA",
        "CTT~1",
        "SE~6~0003",
    ]
    legacy = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~FIRST~92~03",
        "LIN~~MG~AAA",
        "QTY~33~1~EA",
        "CTT~1",
        "SE~6~0001",
        "ST~846~0002",
        "N1~WH~SECOND~92~30",
        "LIN~~MG~BBB",
        "QTY~33~2~EA",
        "CTT~1",
        "SE~6~0002",
    ]
    result = compare_segments(gdl, legacy)
    assert result.paired_block_count == 2
    assert (
        "LIN~~MG~BBB",
        "LIN~~MG~BBB",
        STATUS_MATCH,
        None,
    ) in rows_as_tuples(result)
    assert (
        "LIN~~MG~ORPHAN",
        "",
        STATUS_MISSING_IN_IMPULSE,
        FILL_RED,
    ) in rows_as_tuples(result)


def test_qty_differs_after_lin_match_is_mismatch() -> None:
    gdl = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "LIN~~MG~AAA",
        "QTY~33~1~EA",
        "CTT~1",
        "SE~6~0001",
    ]
    legacy = [
        "ISA~A",
        "GS~A",
        "ST~846~0001",
        "N1~WH~WH1~92~03",
        "LIN~~MG~AAA",
        "QTY~33~9~EA",
        "CTT~1",
        "SE~6~0001",
    ]
    result = compare_segments(gdl, legacy)
    assert (
        "LIN~~MG~AAA",
        "LIN~~MG~AAA",
        STATUS_MATCH,
        None,
    ) in rows_as_tuples(result)
    assert (
        "QTY~33~1~EA",
        "QTY~33~9~EA",
        STATUS_MISMATCH,
        FILL_ORANGE,
    ) in rows_as_tuples(result)


def test_parse_edi_document_reads_lin_qty_pairs() -> None:
    document = parse_edi_document(
        [
            "ISA~A",
            "GS~A",
            "ST~846~0001",
            "N1~WH~WH1~92~03",
            "LIN~~MG~AAA",
            "QTY~33~1~EA",
            "CTT~1",
            "SE~6~0001",
            "GE~1~1",
            "IEA~1~1",
        ]
    )
    assert document.isa == "ISA~A"
    assert document.gs == "GS~A"
    assert len(document.blocks) == 1
    assert document.blocks[0].n1 == "N1~WH~WH1~92~03"
    assert document.blocks[0].items[0].lin == "LIN~~MG~AAA"
    assert document.blocks[0].items[0].qty == "QTY~33~1~EA"
    assert document.ge == "GE~1~1"
    assert document.iea == "IEA~1~1"


def test_empty_inputs_produce_empty_report() -> None:
    result = compare_segments([], [])
    assert result.rows == []
    assert result.gdl_line_count == 0
    assert result.legacy_line_count == 0


def test_read_segment_lines_keeps_inner_spaces_and_splits_crlf(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_bytes(b"N4~CP~0  ~~WH~00\r\nQTY~33~0~EA\r\n")
    assert read_segment_lines(path) == ["N4~CP~0  ~~WH~00", "QTY~33~0~EA"]


def test_read_segment_lines_skips_empty_lines(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("ST~846~0001\n\n\nIEA~1~1\n\n", encoding="utf-8")
    assert read_segment_lines(path) == ["ST~846~0001", "IEA~1~1"]


def test_timestamped_output_path_inserts_local_timestamp() -> None:
    when = datetime(2026, 9, 29, 13, 4, 45)
    path = timestamped_output_path(Path("reports/segment_comparison.xlsx"), when=when)
    assert path == Path("reports/segment_comparison_20260929_130445.xlsx")


def test_excel_report_headers_status_and_fill_colors(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    gdl_lines = ["ISA~GDL", "GS~SAME"]
    legacy_lines = ["ISA~LEG", "GS~SAME"]
    result = compare_segments(gdl_lines, legacy_lines)
    output = tmp_path / "report.xlsx"
    write_excel_report(
        result,
        output,
        gdl_lines=gdl_lines,
        legacy_lines=legacy_lines,
        gdl_source="local/gdl.txt",
        legacy_source="local/legacy.txt",
    )

    workbook = openpyxl.load_workbook(output)
    assert workbook.sheetnames == ["Comparison", "Summary", "GDL File", "Legacy File"]
    sheet = workbook["Comparison"]
    assert [cell.value for cell in sheet[1]] == ["GDL Segment", "Legacy Segment", "status"]
    assert [sheet.cell(row=2, column=j).value for j in range(1, 4)] == [
        "ISA~GDL",
        "ISA~LEG",
        STATUS_MISMATCH,
    ]
    assert [sheet.cell(row=3, column=j).value for j in range(1, 4)] == [
        "GS~SAME",
        "GS~SAME",
        STATUS_MATCH,
    ]
    assert sheet.cell(row=2, column=3).fill.fgColor.rgb.endswith("FFC000")

    summary = workbook["Summary"]
    metrics = {
        summary.cell(row=i, column=1).value: summary.cell(row=i, column=2).value
        for i in range(2, 12)
    }
    assert metrics["MATCH"] == 1
    assert metrics["MISMATCH"] == 1

    gdl_sheet = workbook["GDL File"]
    assert gdl_sheet.cell(row=1, column=2).value == "local/gdl.txt"
    assert [gdl_sheet.cell(row=i, column=2).value for i in range(3, 5)] == gdl_lines
    legacy_sheet = workbook["Legacy File"]
    assert legacy_sheet.cell(row=1, column=2).value == "local/legacy.txt"
    assert [legacy_sheet.cell(row=i, column=2).value for i in range(3, 5)] == legacy_lines


def test_main_writes_a_timestamped_excel_file(tmp_path: Path) -> None:
    from compare_segments import main

    gdl = tmp_path / "gdl.txt"
    legacy = tmp_path / "legacy.txt"
    content = "ISA~A\nGS~A\nST~846~0001\nN1~WH~WH1~92~03\nCTT~0\nSE~4~0001\n"
    gdl.write_text(content, encoding="utf-8")
    legacy.write_text(content, encoding="utf-8")
    output = tmp_path / "report.xlsx"

    assert main(["--gdl", str(gdl), "--legacy", str(legacy), "-o", str(output)]) == 0
    reports = list(tmp_path.glob("report_*.xlsx"))
    assert len(reports) == 1
    assert reports[0].name.startswith("report_")
    assert not output.exists()
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(reports[0])
    assert workbook.sheetnames == ["Comparison", "Summary", "GDL File", "Legacy File"]
    assert workbook["GDL File"].cell(row=3, column=2).value == "ISA~A"
    assert workbook["Legacy File"].cell(row=3, column=2).value == "ISA~A"


def test_prompt_local_file_picks_listed_path_and_custom_path(tmp_path: Path) -> None:
    from compare_segments import prompt_local_file

    first = tmp_path / "aaa.txt"
    second = tmp_path / "bbb.txt"
    custom = tmp_path / "custom.txt"
    first.write_text("ISA~A\n", encoding="utf-8")
    second.write_text("ISA~B\n", encoding="utf-8")
    custom.write_text("ISA~C\n", encoding="utf-8")

    picked = prompt_local_file("GDL", tmp_path, input_func=lambda _prompt: "1")
    assert picked == first

    answers = iter(["3", str(custom)])
    picked_custom = prompt_local_file(
        "Legacy", tmp_path, input_func=lambda _prompt: next(answers)
    )
    assert picked_custom == custom


def test_resolve_side_source_uses_local_path_and_sftp_filename() -> None:
    from compare_segments import parse_args, resolve_side_source

    local_args = parse_args(["--gdl", "gdl.txt", "--legacy-file", "APPLE_846.txt"])
    assert resolve_side_source(local_args, "gdl") == "local"
    assert resolve_side_source(local_args, "legacy") == "sftp"

    prompted = parse_args([])
    answers = iter(["2", "1"])
    assert resolve_side_source(prompted, "gdl", input_func=lambda _prompt: next(answers)) == "sftp"
    assert resolve_side_source(prompted, "legacy", input_func=lambda _prompt: next(answers)) == "local"
