"""Audit-log read shapes (`docs/research/enterprise-gaps-plan.md` Pass B,
feature-matrix gap #52).

The table is append-only and enforced as such by the database (0001 adds
rules turning UPDATE/DELETE into no-ops and revokes both privileges), so
there is nothing here but reads.

Keyset, not offset, pagination — deliberately different from the
`{items: [...]}` shape every other list endpoint uses. Those list bounded
sets a tenant curates by hand (articles, quizzes, templates); the audit
log only ever grows, is already thousands of rows in a dev database, and
is read newest-first while new rows are being written to the head. An
OFFSET walk over that either skips or repeats rows the moment anything
is logged mid-pagination. The cursor is opaque on purpose: it encodes
`(created_at, id)`, and a client that parsed it would be depending on
ordering internals rather than asking for the next page.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    # Masked, never the raw address — the audit reader is answering
    # "who did this" at the level of an account, and a compliance
    # export should not become a second copy of the user table.
    actor_email: str | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    user_agent: str | None


class AuditEventsPage(BaseModel):
    items: list[AuditEventRow]
    # Null when this is the last page. Pass it back as `cursor` for the
    # next one.
    next_cursor: str | None


class AuditActionsResponse(BaseModel):
    """The action values actually present for this tenant, so the filter
    dropdown offers what exists rather than a hardcoded list that drifts
    from `AuditAction` every time someone adds a constant."""

    actions: list[str]


__all__ = ["AuditActionsResponse", "AuditEventRow", "AuditEventsPage"]
