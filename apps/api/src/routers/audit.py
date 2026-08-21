"""The audit-log read path (`docs/research/enterprise-gaps-plan.md`
Pass B, feature-matrix gap #52).

`audit_events` has been written to since 0001 and, until now, had no way
to read it back: "advanced audit logs" is an Enterprise-column promise
in `05_COMMERCIAL.md` §3 and the only way to see one was `psql`. These
three GETs are that read path.

`audit:read` is the gate. It already existed (seeded in 0002, held by
`admin` and `super_admin`), so this pass needed no migration — worth
saying because Pass B assumed one.

Deliberately read-only, with no "delete" or "correct" anywhere: the
table refuses UPDATE and DELETE at the database level and a correction
is a new row. Nothing here would work if it tried.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from src.core.deps import CryptoDep, PrincipalDep, SessionDep
from src.schemas.audit import AuditActionsResponse, AuditEventsPage
from src.services import audit_read

router = APIRouter(tags=["audit"])

PERMISSION = "audit:read"

CSV_HEADER = (
    "created_at",
    "action",
    "actor_email",
    "actor_role",
    "actor_user_id",
    "entity_type",
    "entity_id",
    "ip",
    "user_agent",
    "before",
    "after",
)


@router.get(
    "/audit-events",
    response_model=AuditEventsPage,
    summary="The audit log, newest first, filterable and keyset-paginated",
)
async def list_audit_events(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    action: Annotated[str | None, Query(description="Exact action, e.g. auth.login.failed")] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    date_to: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
    limit: Annotated[int, Query(ge=1, le=audit_read.MAX_LIMIT)] = audit_read.DEFAULT_LIMIT,
) -> AuditEventsPage:
    principal.require(PERMISSION)
    start, end = audit_read.day_bounds(
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    return await audit_read.list_events(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=start,
        date_to=end,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/audit-events/actions",
    response_model=AuditActionsResponse,
    summary="Action values present for this tenant, for the filter control",
)
async def audit_actions(principal: PrincipalDep, session: SessionDep) -> AuditActionsResponse:
    principal.require(PERMISSION)
    return AuditActionsResponse(
        actions=await audit_read.distinct_actions(session, tenant_id=principal.tenant_id)
    )


@router.get(
    "/audit-events/export.csv",
    summary="CSV of the audit log under the same filters as the screen",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_audit_events(
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    action: Annotated[str | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
    date_to: Annotated[date | None, Query(description="UTC day, inclusive")] = None,
) -> Response:
    principal.require(PERMISSION)
    start, end = audit_read.day_bounds(
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    rows = await audit_read.export_rows(
        session,
        crypto,
        tenant_id=principal.tenant_id,
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=start,
        date_to=end,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        writer.writerow(
            (
                row.created_at.isoformat(),
                row.action,
                row.actor_email or "",
                row.actor_role or "",
                str(row.actor_user_id) if row.actor_user_id else "",
                row.entity_type or "",
                str(row.entity_id) if row.entity_id else "",
                row.ip or "",
                row.user_agent or "",
                # The before/after JSON is the substance of a change
                # record; a CSV that dropped it would be a list of verbs.
                _json(row.before),
                _json(row.after),
            )
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-events.csv"'},
    )


def _json(value: object) -> str:
    return "" if value is None else json.dumps(value, separators=(",", ":"), sort_keys=True)


__all__ = ["router"]
