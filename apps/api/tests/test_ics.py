"""services/ics.py (P7 phase 3, REQ-WS-05 "send calendar invite") — pure
text generation, no DB/Redis needed, same class of test test_crypto.py
already uses for a dependency-free service module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.services.ics import IcsEvent, build_ics

NOW = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)


def _event(**overrides: object) -> IcsEvent:
    defaults: dict[str, object] = {
        "uid": uuid.UUID("9637d225-154a-49d4-9916-3362bcd51af7"),
        "summary": "Executive Coaching Debrief",
        "description": "A group workshop.",
        "location": None,
        "starts_at": datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
        "ends_at": datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        "organizer_email": "facilitator@example.com",
    }
    defaults.update(overrides)
    return IcsEvent(**defaults)  # type: ignore[arg-type]


def _lines(raw: bytes) -> list[str]:
    return raw.decode("utf-8").split("\r\n")


def test_required_vevent_fields_are_present() -> None:
    out = build_ics(_event(), now=NOW)
    lines = _lines(out)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert "BEGIN:VEVENT" in lines
    assert "UID:9637d225-154a-49d4-9916-3362bcd51af7@ttli" in lines
    assert "DTSTAMP:20260824T000000Z" in lines
    assert "DTSTART:20260908T090000Z" in lines
    assert "DTEND:20260908T100000Z" in lines
    assert "SUMMARY:Executive Coaching Debrief" in lines
    assert "STATUS:CONFIRMED" in lines
    assert "ORGANIZER:mailto:facilitator@example.com" in lines
    assert "END:VEVENT" in lines
    assert lines[-2] == "END:VCALENDAR"  # -1 is the trailing empty split


def test_cancelled_status_is_reflected() -> None:
    out = build_ics(_event(status="CANCELLED", sequence=1), now=NOW)
    lines = _lines(out)
    assert "STATUS:CANCELLED" in lines
    assert "SEQUENCE:1" in lines


def test_reserved_characters_are_escaped() -> None:
    out = build_ics(_event(summary="Debrief, part one; final review\nnext line"), now=NOW)
    text = out.decode("utf-8")
    assert "SUMMARY:Debrief\\, part one\\; final review\\nnext line" in text
    # The raw unescaped characters never appear as real line/field
    # separators — a naive parser splitting on bare "," or ";" would
    # otherwise corrupt the event.
    assert "\nnext line" not in text.replace("\\n", "")


def test_long_lines_are_folded_at_75_octets_with_a_leading_space() -> None:
    long_description = "x" * 200
    out = build_ics(_event(description=long_description), now=NOW)
    raw_lines = out.decode("utf-8").split("\r\n")
    description_lines = []
    capturing = False
    for line in raw_lines:
        if line.startswith("DESCRIPTION:"):
            capturing = True
        elif capturing and not line.startswith(" "):
            break
        if capturing:
            description_lines.append(line)
    assert len(description_lines) > 1, "a 200-char field must fold across multiple lines"
    assert len(description_lines[0].encode("utf-8")) == 75
    for continuation in description_lines[1:]:
        assert continuation.startswith(" ")
        assert len(continuation.encode("utf-8")) <= 75


def test_multibyte_characters_never_split_mid_sequence() -> None:
    """A naive byte-count fold could cut a UTF-8 sequence in half,
    producing invalid text a strict reader can't decode."""
    out = build_ics(_event(summary="café " * 20), now=NOW)
    # Would raise UnicodeDecodeError if any multi-byte character had
    # been split across a fold boundary.
    out.decode("utf-8")


def test_short_lines_are_not_folded() -> None:
    out = build_ics(_event(), now=NOW)
    for line in out.decode("utf-8").split("\r\n"):
        if line.startswith("SUMMARY:"):
            assert len(line.encode("utf-8")) < 75


def test_location_omitted_when_none() -> None:
    out = build_ics(_event(location=None), now=NOW)
    assert "LOCATION:" not in out.decode("utf-8")


def test_location_included_when_set() -> None:
    out = build_ics(_event(location="Boardroom 3, Sandton"), now=NOW)
    assert "LOCATION:Boardroom 3\\, Sandton" in out.decode("utf-8")
