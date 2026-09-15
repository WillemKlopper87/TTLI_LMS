"""Data-subject rights request/response shapes (BACKLOG T12)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EraseAccountRequest(BaseModel):
    # A deliberate extra step, not identity verification (the caller is
    # already authenticated) — a one-click POST to an irreversible
    # action is exactly the shape of request a client-side confirmation
    # dialog exists to prevent from ever reaching the server by accident.
    confirm: bool = Field(
        ..., description="Must be true; a safety rail against an accidental call."
    )


class ConsentRequest(BaseModel):
    purpose: str
    granted: bool


class LegalHoldRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class LegalHoldStatusResponse(BaseModel):
    legal_hold: bool
    legal_hold_reason: str | None
    legal_hold_set_at: str | None
