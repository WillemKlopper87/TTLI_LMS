"""Operations overview and per-course analytics (`docs/research/
enterprise-gaps-plan.md` Pass A) — three read-only, tenant-scoped,
`analytics:view`-gated GETs backing the admin home and the course
reports screen.

**Path deviation, stated rather than buried:** Pass A writes these as
`GET /admin/overview` and `GET /admin/courses/{id}/analytics`. They live
under `/analytics` instead, because every router in this API is named
for its domain rather than for the UI shell that happens to call it
(`/orders`, `/credentials`, `/analytics`), and an `/admin` prefix would
have created a second namespace for the same kind of read against the
same permission. The screens Pass A describes are unchanged.

`analytics:view` is the gate — the same permission the revenue reports
use, seeded in 0002 for admin/super_admin and extended to finance in
0028. The "needs attention" lists carry counts and shallow rows only;
acting on any of them means opening `/admin/payments` or
`/admin/grading`, which enforce `payment:approve` and `quiz:grade`
themselves. Learner identity is masked in the service layer regardless
of caller, because naming a learner is governed by REQ-TEN-03's
manager-visibility rules and this screen carries no such gate.

No `Idempotency-Key`: that middleware gates mutating commerce endpoints
only, and nothing here writes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from src.core.deps import CryptoDep, PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.schemas.operations import (
    CourseAnalyticsResponse,
    CourseSummaryResponse,
    OverviewResponse,
)
from src.services import operations as operations_service

router = APIRouter(prefix="/analytics", tags=["analytics"])

PERMISSION = "analytics:view"


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Operations KPIs and what needs a human today",
)
async def overview(
    principal: PrincipalDep, session: SessionDep, crypto: CryptoDep
) -> OverviewResponse:
    principal.require(PERMISSION)
    return await operations_service.get_overview(session, crypto, tenant_id=principal.tenant_id)


@router.get(
    "/courses",
    response_model=CourseSummaryResponse,
    summary="Every course this tenant can see, with enrolment and completion counts",
)
async def course_summaries(principal: PrincipalDep, session: SessionDep) -> CourseSummaryResponse:
    principal.require(PERMISSION)
    return await operations_service.get_course_summaries(session, tenant_id=principal.tenant_id)


@router.get(
    "/courses/{course_id}",
    response_model=CourseAnalyticsResponse,
    summary="Enrolment funnel, per-lesson drop-off and quiz distribution for one course",
)
async def course_analytics(
    course_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> CourseAnalyticsResponse:
    principal.require(PERMISSION)
    result = await operations_service.get_course_analytics(
        session, tenant_id=principal.tenant_id, course_id=course_id
    )
    if result is None:
        # A course this tenant was never assigned is indistinguishable
        # from one that does not exist — the same refusal `services/
        # catalogue.py` gives, so the endpoint can't be used to probe the
        # global course catalogue.
        raise NotFound("No such course.")
    return result


__all__ = ["router"]
