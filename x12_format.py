#!/usr/bin/env python3
"""X12 detection, trading-partner delimiters, and segment splitting."""

from __future__ import annotations

import os
import re
from pathlib import Path

# MX ANSI X12 trading-partner segment/element separators.
TRADING_PARTNER_CONFIG = {
    "ELO TOUCH": {"element": "|", "sub_element": "<", "segment": "~"},
    "APPLE": {"element": "~", "sub_element": ">", "segment": "?"},
    "LEXMARK": {"element": "~", "sub_element": ">", "segment": "<"},
    "HPE": {"element": "~", "sub_element": ">", "segment": "]"},
    "DELL": {"element": "*", "sub_element": "~", "segment": "¦"},
    "CISCO": {"element": "~", "sub_element": ">", "segment": "\n"},
    "SAMSUNG": {"element": "*", "sub_element": ">", "segment": "~"},
    "ACER": {"element": "~", "sub_element": ">", "segment": "*"},
    "MICROSOFT": {"element": "<", "sub_element": ">", "segment": "~"},
    "JUNIPER": {"element": "~", "sub_element": ">", "segment": "<"},
    "HPI": {"element": "~", "sub_element": ">", "segment": "]"},
    "EPSON": {"element": "*", "sub_element": "~", "segment": "\n"},
}

DEFAULT_X12_DELIMITERS = {"element": "*", "sub_element": ":", "segment": "~"}

_SEGMENT_ID = re.compile(r"^([A-Z][A-Z0-9]{1,2})")


def detect_edi_format(file_content_head: str) -> str:
    head = file_content_head.strip()
    if head.startswith("ISA"):
        return "X12"
    if head.startswith("UNA") or head.startswith("UNB") or head.startswith("UNH"):
        return "EDIFACT"
    if not head:
        return "EMPTY FILE"
    return "UNKNOWN / UNSUPPORTED"


def extract_vendor_name(filename: str) -> str:
    base = os.path.basename(filename)
    parts = base.replace("-", "_").split("_")
    if not parts:
        return base.upper()
    vendor = parts[0].upper()
    if vendor == "ELO" and len(parts) > 1 and parts[1].upper() == "TOUCH":
        return "ELO TOUCH"
    return vendor


def clean_filename(name: str) -> str:
    return name.strip().replace("\r", "").replace("\n", "").lower()


def segment_prefix(line: str) -> str:
    """Return the X12 segment ID, regardless of the partner's element separator."""
    match = _SEGMENT_ID.match(line)
    if match:
        return match.group(1)
    return line.split("~", 1)[0]


def delimiters_from_isa(content: str) -> dict[str, str] | None:
    """Read X12 separators from the ISA envelope when the vendor is unknown."""
    compact = content.replace("\r", "")
    idx = compact.find("ISA")
    if idx < 0:
        return None
    window = compact[idx : idx + 200].replace("\n", "")
    if len(window) < 106 or window[:3] != "ISA":
        return None
    return {
        "element": window[3],
        "sub_element": window[104],
        "segment": window[105],
    }


def x12_delimiters_for(vendor_name: str, content: str) -> dict[str, str]:
    if vendor_name in TRADING_PARTNER_CONFIG:
        return TRADING_PARTNER_CONFIG[vendor_name]
    return delimiters_from_isa(content) or DEFAULT_X12_DELIMITERS


def parse_x12_segments(raw_content: str, vendor_name: str) -> list[str]:
    """Split a wrapped X12 interchange into one segment per list entry."""
    partner = x12_delimiters_for(vendor_name, raw_content)
    separator = partner["segment"]
    if separator == "\n":
        raw_segments = raw_content.replace("\r", "").split(separator)
    else:
        normalized = raw_content.replace("\r", "").replace("\n", "").strip()
        raw_segments = normalized.split(separator)
    return [seg.strip() for seg in raw_segments if seg.strip()]


def read_segment_lines(path: Path) -> list[str]:
    """Read a segment file as individual lines, preserving inner whitespace."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if line != ""]


def load_local_segments(path: Path) -> list[str]:
    """Load a local file as segments, splitting wrapped X12 or EDIFACT when needed."""
    from edifact_format import parse_edifact_segments

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line != ""]
    edi_format = detect_edi_format(text)
    if edi_format == "EDIFACT":
        return parse_edifact_segments(text)
    if edi_format == "X12" and len(lines) <= 3:
        return parse_x12_segments(text, extract_vendor_name(path.name))
    return lines
