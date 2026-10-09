from __future__ import annotations

import io
from pathlib import Path

import pytest

from compare_segments import (
    STATUS_MATCH,
    STATUS_MISMATCH,
    collect_file_pairs,
    compare_segments,
    detect_edi_format,
    extract_vendor_name,
    parse_edi_document,
    parse_x12_segments,
    process_sftp_comparison,
    prompt_sftp_file,
    segment_prefix,
    unique_sheet_name,
    x12_delimiters_for,
)


class DummyHandle(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class DummySFTP:
    def __init__(self, directories: dict[str, list[str]], files: dict[str, bytes]):
        self.directories = directories
        self.files = files

    def listdir(self, path: str) -> list[str]:
        if path not in self.directories:
            raise FileNotFoundError(path)
        return list(self.directories[path])

    def open(self, path: str, mode: str = "rb") -> DummyHandle:
        if path not in self.files:
            raise FileNotFoundError(path)
        return DummyHandle(self.files[path])


def invrpt_edifact(qty: str = "2") -> str:
    return (
        "UNB+UNOA:2+INGRAMMICROSG:ZZ+098533326TST:ZZ+260911:0234+39++INVRPT\n"
        "UNH+1+INVRPT:D:97A:UN\n"
        "BGM+35::6+20260911023420.442+9\n"
        "DTM+91:20260909:102\n"
        "NAD+DS+936142999999::90\n"
        "NAD+MF+SEAGATE::90\n"
        "LIN+1++STFR5000800:MF\n"
        "LOC+14+2030SG01\n"
        "RFF+AEN:1\n"
        f"QTY+17:{qty}:EA\n"
        "RFF+AEN:2\n"
        "QTY+16:0:EA\n"
        "UNT+12+1\n"
        "UNZ+1+39\n"
    )


def apple_x12(qty: str = "1") -> str:
    return (
        "ISA~00~          ~00~          ~01~004919486MX    ~14~060704780001900"
        "~260903~0003~U~00401~000000016~0~P~>?"
        "GS~IB~004919486MX~060704780400~20260903~0003~16~X~004010?"
        "ST~846~0001?"
        "BIA~00~DD~20260903000401~20260903?"
        "N1~WH~INGRAM MICRO BR 03~92~03?"
        "LIN~~MG~AAA~VP~111?"
        f"QTY~33~{qty}~EA?"
        "CTT~1?"
        "SE~8~0001?"
        "GE~1~16?"
        "IEA~1~000000016?"
    )


def test_detect_edi_format_x12_and_edifact() -> None:
    assert detect_edi_format("ISA*00*XX") == "X12"
    assert detect_edi_format("UNA:+.? ") == "EDIFACT"
    assert detect_edi_format("UNB+UNOC") == "EDIFACT"
    assert detect_edi_format("") == "EMPTY FILE"
    assert detect_edi_format("HELLO") == "UNKNOWN / UNSUPPORTED"


def test_extract_vendor_name_handles_elo_touch() -> None:
    assert extract_vendor_name("APPLE_846_MX.txt") == "APPLE"
    assert extract_vendor_name("ELO_TOUCH-INV.edi") == "ELO TOUCH"


def test_parse_x12_segments_uses_apple_question_terminator() -> None:
    segments = parse_x12_segments(apple_x12(), "APPLE")
    assert segments[0].startswith("ISA~")
    assert "ST~846~0001" in segments
    assert "LIN~~MG~AAA~VP~111" in segments
    assert segments[-1].startswith("IEA~")


def test_segment_prefix_works_with_star_element_separator() -> None:
    assert segment_prefix("ISA*00*A") == "ISA"
    assert segment_prefix("LIN*MG*AAA") == "LIN"
    document = parse_edi_document(["ISA*A", "GS*A", "ST*846*0001", "N1*WH*WH1", "SE*4*0001"])
    assert document.isa == "ISA*A"
    assert document.blocks[0].n1 == "N1*WH*WH1"


def test_star_delimited_x12_still_uses_n1_and_lin_rules() -> None:
    gdl = [
        "ISA*A",
        "GS*A",
        "ST*846*0001",
        "N1*WH*WH1",
        "LIN*MG*AAA",
        "QTY*33*1*EA",
        "CTT*1",
        "SE*8*0001",
    ]
    legacy = [
        "ISA*A",
        "GS*A",
        "ST*846*0001",
        "N1*WH*WH1",
        "LIN*MG*AAA",
        "QTY*33*9*EA",
        "CTT*1",
        "SE*8*0001",
    ]
    result = compare_segments(gdl, legacy)
    statuses = {(row.gdl_segment, row.legacy_segment, row.status) for row in result.rows}
    assert ("LIN*MG*AAA", "LIN*MG*AAA", STATUS_MATCH) in statuses
    assert ("QTY*33*1*EA", "QTY*33*9*EA", STATUS_MISMATCH) in statuses


def test_unknown_vendor_reads_delimiters_from_isa() -> None:
    content = apple_x12()
    delimiters = x12_delimiters_for("UNKNOWNVENDOR", content)
    assert delimiters["element"] == "~"
    assert delimiters["segment"] == "?"


def test_collect_file_pairs_compares_x12_and_edifact() -> None:
    gdl_dir = "/GDL/MX/INV"
    legacy_dir = "/ECC_IMPULSE/MX/INV"
    apple = apple_x12().encode("utf-8")
    invrpt = b"UNB+UNOA:2+GDL:ZZ+LEG:ZZ+260911:0234+1++INVRPT'"
    sftp = DummySFTP(
        directories={
            gdl_dir: ["APPLE_846.txt", "VENDOR_EDIFACT.txt", "MIXED.txt", "ONLY_GDL.txt"],
            legacy_dir: ["APPLE_846.txt", "VENDOR_EDIFACT.txt", "MIXED.txt", "ONLY_LEG.txt"],
        },
        files={
            f"{gdl_dir}/APPLE_846.txt": apple,
            f"{legacy_dir}/APPLE_846.txt": apple,
            f"{gdl_dir}/VENDOR_EDIFACT.txt": invrpt,
            f"{legacy_dir}/VENDOR_EDIFACT.txt": invrpt,
            f"{gdl_dir}/MIXED.txt": apple,
            f"{legacy_dir}/MIXED.txt": invrpt,
            f"{gdl_dir}/ONLY_GDL.txt": apple,
            f"{legacy_dir}/ONLY_LEG.txt": apple,
        },
    )
    rows = collect_file_pairs(
        sftp,
        gdl_dir,
        legacy_dir,
        ["APPLE_846.txt", "VENDOR_EDIFACT.txt", "MIXED.txt", "ONLY_GDL.txt"],
        ["APPLE_846.txt", "VENDOR_EDIFACT.txt", "MIXED.txt", "ONLY_LEG.txt"],
    )
    actions = {row.display_name: row.action for row in rows}
    assert actions["APPLE_846.txt"] == "Compared"
    assert actions["VENDOR_EDIFACT.txt"] == "Compared"
    assert actions["MIXED.txt"] == "SKIPPED (unsupported or mixed format)"
    assert actions["ONLY_GDL.txt"] == "Missing in Legacy Folder"
    assert actions["ONLY_LEG.txt"] == "Missing in New GDL Folder"


def test_process_sftp_comparison_writes_selected_files_and_source_sheets(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    gdl_dir = "/GDL/MX/INV"
    legacy_dir = "/ECC_IMPULSE/MX/INV"
    gdl_body = apple_x12("1").encode("utf-8")
    legacy_body = apple_x12("9").encode("utf-8")
    sftp = DummySFTP(
        directories={
            gdl_dir: ["APPLE_846.txt", "VENDOR_EDIFACT.txt"],
            legacy_dir: ["APPLE_846.txt"],
        },
        files={
            f"{gdl_dir}/APPLE_846.txt": gdl_body,
            f"{gdl_dir}/VENDOR_EDIFACT.txt": b"UNB+UNOC:3+",
            f"{legacy_dir}/APPLE_846.txt": legacy_body,
        },
    )
    output = tmp_path / "sftp_report.xlsx"
    assert (
        process_sftp_comparison(
            "MX",
            "INV",
            output,
            sftp=sftp,
            gdl_file="APPLE_846.txt",
            legacy_file="APPLE_846.txt",
        )
        == 0
    )
    reports = list(tmp_path.glob("sftp_report_*.xlsx"))
    assert len(reports) == 1

    workbook = openpyxl.load_workbook(reports[0])
    assert workbook.sheetnames == ["Comparison", "Summary", "GDL File", "Legacy File"]
    statuses = [
        workbook["Comparison"].cell(row=i, column=3).value
        for i in range(2, workbook["Comparison"].max_row + 1)
    ]
    assert STATUS_MISMATCH in statuses
    gdl_values = [
        workbook["GDL File"].cell(row=i, column=2).value
        for i in range(3, workbook["GDL File"].max_row + 1)
    ]
    assert workbook["GDL File"].cell(row=3, column=2).value.startswith("ISA~")
    assert "QTY~33~1~EA" in gdl_values
    assert workbook["Legacy File"].cell(row=3, column=2).value.startswith("ISA~")


def test_process_sftp_comparison_compares_edifact_invrpt(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    gdl_dir = "/GDL/SG/INV"
    legacy_dir = "/ECC_IMPULSE/SG/INV"
    sftp = DummySFTP(
        directories={
            gdl_dir: ["SEAGATE_INVRPT.txt"],
            legacy_dir: ["SEAGATE_INVRPT.txt"],
        },
        files={
            f"{gdl_dir}/SEAGATE_INVRPT.txt": invrpt_edifact("2").encode("utf-8"),
            f"{legacy_dir}/SEAGATE_INVRPT.txt": invrpt_edifact("9").encode("utf-8"),
        },
    )
    output = tmp_path / "edifact_report.xlsx"
    assert (
        process_sftp_comparison(
            "SG",
            "INV",
            output,
            sftp=sftp,
            gdl_file="SEAGATE_INVRPT.txt",
            legacy_file="SEAGATE_INVRPT.txt",
        )
        == 0
    )
    reports = list(tmp_path.glob("edifact_report_*.xlsx"))
    assert len(reports) == 1
    workbook = openpyxl.load_workbook(reports[0])
    statuses = [
        workbook["Comparison"].cell(row=i, column=3).value
        for i in range(2, workbook["Comparison"].max_row + 1)
    ]
    assert STATUS_MISMATCH in statuses
    gdl_values = [
        workbook["GDL File"].cell(row=i, column=2).value
        for i in range(3, workbook["GDL File"].max_row + 1)
    ]
    assert gdl_values[0].startswith("UNB+")
    assert "QTY+17:2:EA" in gdl_values


def test_process_sftp_compare_all_writes_audit_and_vendor_sheets(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    gdl_dir = "/GDL/MX/INV"
    legacy_dir = "/ECC_IMPULSE/MX/INV"
    gdl_body = apple_x12("1").encode("utf-8")
    legacy_body = apple_x12("9").encode("utf-8")
    sftp = DummySFTP(
        directories={
            gdl_dir: ["APPLE_846.txt"],
            legacy_dir: ["APPLE_846.txt"],
        },
        files={
            f"{gdl_dir}/APPLE_846.txt": gdl_body,
            f"{legacy_dir}/APPLE_846.txt": legacy_body,
        },
    )
    output = tmp_path / "sftp_all.xlsx"
    assert process_sftp_comparison("MX", "INV", output, sftp=sftp, compare_all=True) == 0
    reports = list(tmp_path.glob("sftp_all_*.xlsx"))
    assert len(reports) == 1

    workbook = openpyxl.load_workbook(reports[0])
    assert workbook.sheetnames[0] == "File Audit"
    assert "Summary" in workbook.sheetnames
    assert "APPLE" in workbook.sheetnames
    audit = workbook["File Audit"]
    assert audit.cell(row=2, column=7).value == "Compared"
    apple_sheet = workbook["APPLE"]
    statuses = [apple_sheet.cell(row=i, column=3).value for i in range(2, apple_sheet.max_row + 1)]
    assert STATUS_MISMATCH in statuses


def test_prompt_sftp_file_skips_unsupported_then_accepts_edifact() -> None:
    entries = [
        ("NOTES.txt", "UNKNOWN / UNSUPPORTED", "/GDL/MX/INV/NOTES.txt"),
        ("VENDOR_EDIFACT.txt", "EDIFACT", "/GDL/MX/INV/VENDOR_EDIFACT.txt"),
    ]
    answers = iter(["1", "2"])
    name, edi_format, path = prompt_sftp_file(
        "GDL", entries, input_func=lambda _prompt: next(answers)
    )
    assert name == "VENDOR_EDIFACT.txt"
    assert edi_format == "EDIFACT"
    assert path.endswith("VENDOR_EDIFACT.txt")


def test_unique_sheet_name_avoids_collisions_and_invalid_chars() -> None:
    used: set[str] = set()
    first = unique_sheet_name("APPLE", used)
    second = unique_sheet_name("APPLE", used)
    weird = unique_sheet_name("A[B]*C?", used)
    assert first == "APPLE"
    assert second == "APPLE_2"
    assert "[" not in weird
    assert "*" not in weird
