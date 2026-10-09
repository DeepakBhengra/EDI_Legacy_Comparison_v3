#!/usr/bin/env python3
"""EDIFACT detection, UNA delimiters, and segment splitting."""

from __future__ import annotations

from pathlib import Path

DEFAULT_EDIFACT_DELIMITERS = {
    "element": "+",
    "component": ":",
    "release": "?",
    "segment": "'",
}


def delimiters_from_una(content: str) -> dict[str, str] | None:
    """Read EDIFACT separators from a UNA service string when present."""
    stripped = content.lstrip("\r\n")
    if not stripped.startswith("UNA") or len(stripped) < 9:
        return None
    una = stripped[3:9]
    return {
        "component": una[0],
        "element": una[1],
        "decimal": una[2],
        "release": una[3],
        "repeat": una[4],
        "segment": una[5],
    }


def edifact_tag(line: str) -> str:
    """Return the 3-character EDIFACT segment tag."""
    text = line.strip()
    if len(text) >= 3:
        return text[:3].upper()
    return text.upper()


def _split_with_release(text: str, separator: str, release: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if release and char == release:
            escaped = True
            continue
        if char == separator:
            piece = "".join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        current.append(char)
    piece = "".join(current).strip()
    if piece:
        parts.append(piece)
    return parts


def parse_edifact_segments(raw_content: str) -> list[str]:
    """Split an EDIFACT interchange into one segment per list entry.

    Uses UNA separators when present. Line-oriented dumps (one segment per
    newline, as in the INVRPT sample) are kept as lines. Wrapped files that
    use apostrophe terminators are split on that terminator.
    """
    text = raw_content.replace("\r", "")
    delimiters = delimiters_from_una(text) or DEFAULT_EDIFACT_DELIMITERS
    segment_sep = delimiters["segment"]
    release = delimiters["release"]

    body = text
    if text.lstrip().startswith("UNA") and len(text.lstrip()) >= 9:
        stripped = text.lstrip()
        body = stripped[9:].lstrip("\n")

    lines = [line.strip() for line in body.split("\n") if line.strip()]
    # Already one segment per line (INVRPT dumps). Do not re-split on apostrophes
    # that may appear inside free-text IMD/NAD fields.
    if len(lines) > 1:
        return [line.rstrip(segment_sep).strip() if segment_sep != "\n" else line for line in lines]

    compact = body.replace("\n", "")
    if segment_sep != "\n" and segment_sep in compact:
        return _split_with_release(compact, segment_sep, release)

    return lines


def load_edifact_segments(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_edifact_segments(text)


def edifact_element(line: str, index: int, element: str = "+") -> str:
    """Return a 0-based data element after the segment tag."""
    parts = line.split(element)
    if index + 1 >= len(parts):
        return ""
    return parts[index + 1]


def edifact_qualifier(line: str, element: str = "+") -> str:
    """Return the first qualifier after the tag (NAD+DS, DTM+91, QTY+17)."""
    value = edifact_element(line, 0, element)
    return value.split(":")[0]
