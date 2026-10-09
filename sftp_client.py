#!/usr/bin/env python3
"""SFTP connectivity and remote X12 file listing/download."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from getpass import getpass

from cli_prompts import prompt_sftp_file
from edi846_compare import ComparisonResult, compare_segments
from x12_format import (
    clean_filename,
    detect_edi_format,
    extract_vendor_name,
    parse_x12_segments,
)

SFTP_HOST = os.environ.get("SFTP_HOST", "venus.ingrammicro.com")
SFTP_PORT = int(os.environ.get("SFTP_PORT", "22"))
SFTP_USER = os.environ.get("SFTP_USER", "EDI_REPORT")
SFTP_PASSWORD_DEFAULT = os.environ.get("SFTP_PASSWORD", "")


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
            "paramiko is required for SFTP and is not installed in this Python:\n"
            f"  {sys.executable}\n"
            "Install it with that same interpreter:\n"
            f'  "{sys.executable}" -m pip install -r requirements.txt\n'
            "Or compare local files without SFTP:\n"
            f'  "{sys.executable}" compare_segments.py --local'
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


def open_sftp_or_fail(password: str | None):
    sftp, transport = get_sftp_client(password)
    if not sftp:
        return None, None
    return sftp, transport


def close_sftp(sftp, transport) -> None:
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


def resolve_sftp_folder(sftp, country: str, report_type: str, side: str) -> tuple[list[str], str]:
    if side == "gdl":
        base = f"/GDL/{country}/{report_type}"
    else:
        base = f"/ECC_IMPULSE/{country}/{report_type}"
    return safe_listdir(sftp, base)


def annotate_sftp_files(sftp, directory: str, names: list[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for name in names:
        if not name:
            continue
        path = f"{directory}/{name}"
        edi_format = read_file_header_safely(sftp, path)
        rows.append((name, edi_format, path))
    return rows


def lookup_sftp_entry(
    entries: list[tuple[str, str, str]],
    filename: str,
) -> tuple[str, str, str] | None:
    wanted = clean_filename(filename)
    for name, edi_format, path in entries:
        if clean_filename(name) == wanted or name == filename:
            return name, edi_format, path
    return None


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
    from excel_report import unique_sheet_name

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
