#!/usr/bin/env python3
"""Interactive menus for country, report type, and file selection."""

from __future__ import annotations

from pathlib import Path


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


def list_local_input_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
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
        if edi_format not in {"X12", "EDIFACT"}:
            print(f"[Invalid Input] {name} is {edi_format}. Choose an X12 or EDIFACT file.\n")
            continue
        return name, edi_format, path
