"""Shared error type for the workshops package (0018, REQ-WS-01..09) — its
own leaf module so authoring/booking/attendance/reporting can each raise
it without importing one another."""

from __future__ import annotations

from src.core.errors import AppError


class WorkshopError(AppError):
    """A refusal in the booking flow — full session, already booked,
    outside availability, or a state transition that doesn't apply."""

    code = "WORKSHOP_ERROR"


__all__ = ["WorkshopError"]
