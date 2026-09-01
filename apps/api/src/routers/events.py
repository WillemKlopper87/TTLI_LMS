"""Public, domain-agnostic event ingestion. Currently just the pageview
beacon behind site-traffic reporting (checklist item 20 follow-up,
01_PRD.md §5.11's first-party-analytics decision) — kept separate from
articles.py/podcasts.py's own event endpoints since a pageview isn't
tied to one resource type the way an article read or a podcast play is.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from src.core.deps import SessionDep, TenantDep
from src.schemas.events import PageViewRequest
from src.services import events, rate_limit

router = APIRouter(tags=["events"])


@router.post(
    "/public/events/pageview",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Log a pageview on a public marketing page, no auth required",
    dependencies=[Depends(rate_limit.rate_limited(rate_limit.PAGE_EVENTS))],
)
async def log_pageview(
    body: PageViewRequest,
    session: SessionDep,
    tenant: TenantDep,
) -> None:
    await events.record(
        session,
        tenant_id=tenant.id,
        event_name=events.EventName.PAGE_VIEWED,
        properties={"path": body.path, "referrer": body.referrer},
    )


__all__ = ["router"]
