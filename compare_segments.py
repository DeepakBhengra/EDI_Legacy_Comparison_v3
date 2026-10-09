#!/usr/bin/env python3
"""CLI for GDL vs Legacy X12 846 comparison.

Comparison rules live in edi846_compare.py, X12 splitting in x12_format.py,
SFTP in sftp_client.py, and Excel output in excel_report.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli_prompts import (
    prompt_country,
    prompt_input_source,
    prompt_local_file,
    prompt_report_type,
    prompt_sftp_file,
)
from edi846_compare import (
    FILL_ORANGE,
    FILL_RED,
    STATUS_MATCH,
    STATUS_MISMATCH,
    STATUS_MISSING_IN_GDL,
    STATUS_MISSING_IN_IMPULSE,
    ComparisonResult,
    compare_segments,
    parse_edi_document,
)
from excel_report import (
    timestamped_output_path,
    unique_sheet_name,
    write_excel_report,
    write_sftp_excel_report,
)
from sftp_client import (
    collect_file_pairs,
    close_sftp,
    compare_x12_pairs,
    get_sftp_client,
    load_sftp_selected_file,
    open_sftp_or_fail,
    safe_listdir,
)
from x12_format import (
    detect_edi_format,
    extract_vendor_name,
    load_local_segments,
    parse_x12_segments,
    read_segment_lines,
    segment_prefix,
    x12_delimiters_for,
)


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
            close_sftp(sftp, transport)


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
        close_sftp(sftp, transport)

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
