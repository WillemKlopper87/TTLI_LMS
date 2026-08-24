"""ICS calendar-invite generation (P7, docs/BACKLOG.md; REQ-WS-05's
"send calendar invite"). Hand-rolled `VCALENDAR`/`VEVENT` text, no new
dependency — the same "one format, don't add a library for one
function" reasoning `services/oidc.py`'s own docstring already
established for OAuth2, and R1's SVG line chart before that. RFC 5545
is a plain text format; the parts worth getting right by hand are line
folding (§3.1) and value escaping (§3.3.11), both done below.

This is the fallback every session gets regardless of meeting
provider — a manually-run session has no Outlook invite of its own to
send (`services/meeting/manual.py` never touches a calendar), and even
a Teams-provider session (Phase 5) benefits from a downloadable file a
learner can re-import if they missed the original invite email.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

_FOLD_WIDTH = 75


def _escape(value: str) -> str:
    """RFC 5545 §3.3.11: backslash, comma, semicolon and newline are the
    four characters `TEXT` values must escape."""
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 §3.1: a content line longer than 75 octets is split
    across multiple lines, each continuation starting with a single
    space. Folding by UTF-8 byte length, not character count — the
    spec's "octets" — so a line of multi-byte characters folds at the
    same byte boundary a strict reader expects."""
    encoded = line.encode("utf-8")
    if len(encoded) <= _FOLD_WIDTH:
        return line
    chunks: list[str] = []
    remaining = encoded
    first = True
    while remaining:
        width = _FOLD_WIDTH if first else _FOLD_WIDTH - 1
        # Never split a multi-byte UTF-8 sequence in half. Only the
        # backward-scan needs a bounds guard: cut == len(remaining)
        # means this chunk takes everything left, so remaining[cut]
        # would index one past the end — nothing to re-check there,
        # the sequence can't be split if there's nothing after it.
        cut = min(width, len(remaining))
        while cut > 0 and cut < len(remaining) and (remaining[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(remaining[:cut].decode("utf-8"))
        remaining = remaining[cut:]
        first = False
    return "\r\n ".join(chunks)


def _dt(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True, slots=True)
class IcsEvent:
    uid: uuid.UUID
    summary: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    organizer_email: str
    status: str = "CONFIRMED"
    sequence: int = 0


def build_ics(event: IcsEvent, *, now: datetime) -> bytes:
    """One `VEVENT` per file — a booking is one session, not a series.
    `now` is passed in rather than read here, matching this codebase's
    consistent "don't call the wall clock from inside a pure function"
    style (`datetime.now(UTC)` stays the caller's concern, same as
    every other service module)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TTLI//Workshops//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event.uid}@ttli",
        f"DTSTAMP:{_dt(now)}",
        f"DTSTART:{_dt(event.starts_at)}",
        f"DTEND:{_dt(event.ends_at)}",
        f"SEQUENCE:{event.sequence}",
        f"STATUS:{event.status}",
        f"SUMMARY:{_escape(event.summary)}",
    ]
    if event.description:
        lines.append(f"DESCRIPTION:{_escape(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{_escape(event.location)}")
    lines.append(f"ORGANIZER:mailto:{event.organizer_email}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")


__all__ = ["IcsEvent", "build_ics"]
