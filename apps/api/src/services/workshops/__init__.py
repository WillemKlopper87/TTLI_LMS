"""Workshops, facilitators, booking (02 §9, REQ-WS-01 through REQ-WS-09).
See `0018`'s migration docstring for what this sprint deliberately
deferred and why.

Split into `authoring`/`booking`/`attendance`/`reporting` submodules
(TTLI_Audit_Report_2026-09-02.md M6 — the former single 1358-line
`services/workshops.py` mixed authorization, state changes, provider
calls and reporting in one file). Provider-sync calls (Teams/Zoom/Meet
meeting create/cancel/attendee edits) stay textually inside `booking.py`'s
own functions, in the same transaction that owns them — the audit's own
caution against crossing that boundary just to tidy up file organisation.

Every name below is re-exported so `from src.services import workshops as
workshops_service` (`routers/workshops.py`, unchanged) keeps resolving
`workshops_service.<name>` exactly as it did before the split — confirmed
by reading every one of that router's ~27 call sites, all plain attribute
access, never `from ... import <name>` or `import *`.

This `__all__` also fixes four names the pre-split file's own `__all__`
had silently dropped (`book_open_slot`, `list_open_slots`,
`list_coaching_facilitators`, `list_public_one_on_one_workshops`) —
harmless before now since attribute access doesn't consult `__all__`,
but there's no reason to carry the staleness forward.
"""

from __future__ import annotations

from src.services.workshops.attendance import RosterRow, list_roster, mark_attendance
from src.services.workshops.authoring import (
    add_availability,
    add_session_facilitator,
    create_facilitator,
    create_session,
    create_workshop,
    list_availability,
    list_workshops,
    remove_session_facilitator,
    update_workshop,
)
from src.services.workshops.booking import (
    book_open_slot,
    book_session,
    cancel_booking,
    cancel_session,
    list_open_slots,
    reschedule_booking,
)
from src.services.workshops.errors import WorkshopError
from src.services.workshops.reporting import (
    BookingIcsContext,
    CoachingFacilitatorRow,
    FacilitatorRow,
    OwnBookingRow,
    get_booking_ics_context,
    list_coaching_facilitators,
    list_facilitators,
    list_own_bookings,
    list_public_one_on_one_workshops,
    list_public_sessions,
    list_session_facilitators,
    list_sessions,
    seat_counts,
)

__all__ = [
    "BookingIcsContext",
    "CoachingFacilitatorRow",
    "FacilitatorRow",
    "OwnBookingRow",
    "RosterRow",
    "WorkshopError",
    "add_availability",
    "add_session_facilitator",
    "book_open_slot",
    "book_session",
    "cancel_booking",
    "cancel_session",
    "create_facilitator",
    "create_session",
    "create_workshop",
    "get_booking_ics_context",
    "list_availability",
    "list_coaching_facilitators",
    "list_facilitators",
    "list_open_slots",
    "list_own_bookings",
    "list_public_one_on_one_workshops",
    "list_public_sessions",
    "list_roster",
    "list_session_facilitators",
    "list_sessions",
    "list_workshops",
    "mark_attendance",
    "remove_session_facilitator",
    "reschedule_booking",
    "seat_counts",
    "update_workshop",
]
