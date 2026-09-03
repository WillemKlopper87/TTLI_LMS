"""Learning-path authoring and tenant-visibility assignment (`docs/
BACKLOG.md` P5). Same permission split `routers/courses.py` established:
`course:edit` gates structure, `course:publish` gates publish/unpublish/
tenant-assignment — a path bundles courses, it doesn't author their
content, so it never needs any assessment/media-attach permission.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from src.core.deps import CryptoDep, PrincipalDep, SessionDep, SettingsDep, StorageDep, TenantDep
from src.core.errors import NotFound
from src.models.audit import AuditAction
from src.models.course import Course
from src.models.learning_path import LearningPath, LearningPathCourse
from src.schemas.courses import PublicPrice
from src.schemas.learning_paths import (
    AddPathCourseRequest,
    LearningPathCreateRequest,
    LearningPathResponse,
    LearningPathsPageResponse,
    LearningPathUpdateRequest,
    OwnPathEnrolmentResponse,
    PathCourseProgressRow,
    PathCourseRow,
    PathCoursesResponse,
    PathProgressResponse,
    PathReadinessCheckRow,
    PathReadinessResponse,
    PathTenantAssignmentResponse,
    PathTenantAssignmentRow,
    PathTenantAssignmentsPageResponse,
    PublicPathCard,
    PublicPathCourseRow,
    PublicPathDetailResponse,
    PublicPathsResponse,
    ReorderPathCoursesRequest,
    TenantAssignmentCreateRequest,
)
from src.services import audit, rate_limit
from src.services import learning_paths as paths_service
from src.services.courses import PublicPriceRow

router = APIRouter(tags=["learning-paths"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _path_response(path: LearningPath) -> LearningPathResponse:
    return LearningPathResponse(
        id=str(path.id),
        slug=path.slug,
        title=path.title,
        description=path.description,
        state=path.state,
        certificate_template_id=(
            str(path.certificate_template_id) if path.certificate_template_id else None
        ),
    )


def _course_row(member: LearningPathCourse, course: Course) -> PathCourseRow:
    return PathCourseRow(
        course_id=str(course.id),
        title=course.title,
        slug=course.slug,
        state=course.state,
        level=course.level,
        position=member.position,
    )


@router.get("/learning-paths", response_model=LearningPathsPageResponse)
async def list_learning_paths(
    principal: PrincipalDep, session: SessionDep
) -> LearningPathsPageResponse:
    principal.require("course:view")
    paths = await paths_service.list_learning_paths(session, tenant_id=principal.tenant_id)
    return LearningPathsPageResponse(items=[_path_response(p) for p in paths])


@router.post(
    "/learning-paths", response_model=LearningPathResponse, status_code=status.HTTP_201_CREATED
)
async def create_learning_path(
    body: LearningPathCreateRequest, principal: PrincipalDep, session: SessionDep
) -> LearningPathResponse:
    principal.require("course:edit")
    path = await paths_service.create_learning_path(
        session,
        tenant_id=principal.tenant_id,
        title=body.title,
        slug=body.slug,
        description=body.description,
    )
    return _path_response(path)


@router.get("/learning-paths/{learning_path_id}", response_model=LearningPathResponse)
async def get_learning_path(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> LearningPathResponse:
    principal.require("course:view")
    path = await paths_service.get_learning_path(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    return _path_response(path)


@router.patch("/learning-paths/{learning_path_id}", response_model=LearningPathResponse)
async def update_learning_path(
    learning_path_id: str,
    body: LearningPathUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> LearningPathResponse:
    principal.require("course:edit")
    path = await paths_service.update_learning_path(
        session,
        learning_path_id=_parse_uuid(learning_path_id),
        tenant_id=principal.tenant_id,
        title=body.title,
        description=body.description,
        certificate_template_id=(
            _parse_uuid(body.certificate_template_id) if body.certificate_template_id else None
        ),
    )
    return _path_response(path)


@router.post(
    "/learning-paths/{learning_path_id}/clear-certificate-template",
    response_model=LearningPathResponse,
)
async def clear_path_certificate_template(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> LearningPathResponse:
    principal.require("course:edit")
    path = await paths_service.clear_certificate_template(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    return _path_response(path)


@router.get("/learning-paths/{learning_path_id}/courses", response_model=PathCoursesResponse)
async def list_path_courses(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> PathCoursesResponse:
    principal.require("course:view")
    rows = await paths_service.list_path_courses(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    return PathCoursesResponse(items=[_course_row(member, course) for member, course in rows])


@router.post(
    "/learning-paths/{learning_path_id}/courses",
    response_model=PathCoursesResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_path_course(
    learning_path_id: str,
    body: AddPathCourseRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> PathCoursesResponse:
    principal.require("course:edit")
    path_id = _parse_uuid(learning_path_id)
    await paths_service.add_course_to_path(
        session,
        learning_path_id=path_id,
        tenant_id=principal.tenant_id,
        course_id=_parse_uuid(body.course_id),
    )
    rows = await paths_service.list_path_courses(
        session, learning_path_id=path_id, tenant_id=principal.tenant_id
    )
    return PathCoursesResponse(items=[_course_row(member, course) for member, course in rows])


@router.delete(
    "/learning-paths/{learning_path_id}/courses/{course_id}",
    response_model=PathCoursesResponse,
)
async def remove_path_course(
    learning_path_id: str, course_id: str, principal: PrincipalDep, session: SessionDep
) -> PathCoursesResponse:
    principal.require("course:edit")
    path_id = _parse_uuid(learning_path_id)
    await paths_service.remove_course_from_path(
        session,
        learning_path_id=path_id,
        tenant_id=principal.tenant_id,
        course_id=_parse_uuid(course_id),
    )
    rows = await paths_service.list_path_courses(
        session, learning_path_id=path_id, tenant_id=principal.tenant_id
    )
    return PathCoursesResponse(items=[_course_row(member, course) for member, course in rows])


@router.post(
    "/learning-paths/{learning_path_id}/courses/reorder", response_model=PathCoursesResponse
)
async def reorder_path_courses(
    learning_path_id: str,
    body: ReorderPathCoursesRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> PathCoursesResponse:
    principal.require("course:edit")
    rows = await paths_service.reorder_path_courses(
        session,
        learning_path_id=_parse_uuid(learning_path_id),
        tenant_id=principal.tenant_id,
        ordered_course_ids=[_parse_uuid(x) for x in body.ordered_course_ids],
    )
    return PathCoursesResponse(items=[_course_row(member, course) for member, course in rows])


@router.get("/learning-paths/{learning_path_id}/readiness", response_model=PathReadinessResponse)
async def get_path_readiness(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> PathReadinessResponse:
    principal.require("course:edit")
    report = await paths_service.get_path_readiness(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    return PathReadinessResponse(
        learning_path_id=learning_path_id,
        publishable=report.publishable,
        course_count=report.course_count,
        checks=[
            PathReadinessCheckRow(code=c.code, level=c.level, ok=c.ok, message=c.message)
            for c in report.checks
        ],
    )


@router.post("/learning-paths/{learning_path_id}/publish", response_model=LearningPathResponse)
async def publish_learning_path(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> LearningPathResponse:
    principal.require("course:publish")
    path = await paths_service.publish_learning_path(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    # Publishing changes what a tenant can assign/sell — same reasoning
    # routers/courses.py::publish_course already logs this for.
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.LEARNING_PATH_PUBLISHED,
        actor_user_id=principal.user_id,
        entity_type="learning_path",
        entity_id=path.id,
        after={"title": path.title, "state": path.state},
    )
    return _path_response(path)


@router.post("/learning-paths/{learning_path_id}/unpublish", response_model=LearningPathResponse)
async def unpublish_learning_path(
    learning_path_id: str, principal: PrincipalDep, session: SessionDep
) -> LearningPathResponse:
    principal.require("course:publish")
    path = await paths_service.unpublish_learning_path(
        session, learning_path_id=_parse_uuid(learning_path_id), tenant_id=principal.tenant_id
    )
    await audit.record(
        session,
        tenant_id=principal.tenant_id,
        action=AuditAction.LEARNING_PATH_UNPUBLISHED,
        actor_user_id=principal.user_id,
        entity_type="learning_path",
        entity_id=path.id,
        after={"title": path.title, "state": path.state},
    )
    return _path_response(path)


@router.post(
    "/learning-paths/{learning_path_id}/tenant-assignments",
    response_model=PathTenantAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_path_to_tenant(
    learning_path_id: str,
    body: TenantAssignmentCreateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> PathTenantAssignmentResponse:
    principal.require("course:publish")
    assignment = await paths_service.assign_path_to_tenant(
        session,
        learning_path_id=_parse_uuid(learning_path_id),
        tenant_id=principal.tenant_id,
        is_bespoke=body.is_bespoke,
    )
    return PathTenantAssignmentResponse(
        id=str(assignment.id),
        tenant_id=str(assignment.tenant_id),
        learning_path_id=str(assignment.learning_path_id),
        is_bespoke=assignment.is_bespoke,
    )


@router.get("/tenant-path-assignments", response_model=PathTenantAssignmentsPageResponse)
async def list_tenant_path_assignments(
    principal: PrincipalDep, session: SessionDep
) -> PathTenantAssignmentsPageResponse:
    """The path twin of `courses.py::list_tenant_assignments` — the read
    half of tenant assignment that `assign_path_to_tenant` never had
    (F6, docs/research/p5-review-findings.md): before this, the admin
    editor's "Assign to this tenant" gave only a transient success
    notice and could never show whether a path was already assigned."""
    principal.require("course:view")
    rows = await paths_service.list_tenant_path_assignments(session, tenant_id=principal.tenant_id)
    return PathTenantAssignmentsPageResponse(
        items=[
            PathTenantAssignmentRow(
                id=str(assignment.id),
                learning_path_id=str(path.id),
                learning_path_title=path.title,
                is_bespoke=assignment.is_bespoke,
            )
            for assignment, path in rows
        ]
    )


def _public_price(row: PublicPriceRow | None) -> PublicPrice | None:
    if row is None:
        return None
    return PublicPrice(
        product_id=str(row.product_id),
        price_id=str(row.price_id),
        currency=row.currency,
        unit_amount=row.unit_amount,
        tax_behaviour=row.tax_behaviour,
        includes_vat=row.includes_vat,
    )


@router.get(
    "/public/learning-paths",
    response_model=PublicPathsResponse,
    summary="Every published learning path this tenant offers, no auth required",
    dependencies=[Depends(rate_limit.rate_limited(rate_limit.PUBLIC_READ))],
)
async def list_public_paths(session: SessionDep, tenant: TenantDep) -> PublicPathsResponse:
    paths = await paths_service.list_public_paths(session, tenant_id=tenant.id)
    path_ids = [p.id for p in paths]
    prices = await paths_service.public_prices_for_paths(
        session, tenant_id=tenant.id, path_ids=path_ids
    )
    counts = await paths_service.course_counts_for_paths(session, path_ids=path_ids)
    return PublicPathsResponse(
        items=[
            PublicPathCard(
                id=str(path.id),
                slug=path.slug,
                title=path.title,
                description=path.description,
                course_count=counts.get(path.id, 0),
                has_certificate=path.certificate_template_id is not None,
                price=_public_price(prices.get(path.id)),
            )
            for path in paths
        ]
    )


@router.get(
    "/public/learning-paths/{learning_path_id}",
    response_model=PublicPathDetailResponse,
    summary="A published learning path's member courses, no auth required",
    dependencies=[Depends(rate_limit.rate_limited(rate_limit.PUBLIC_READ))],
)
async def get_public_path(
    learning_path_id: str, session: SessionDep, tenant: TenantDep
) -> PublicPathDetailResponse:
    path, members = await paths_service.get_public_path(
        session, tenant_id=tenant.id, learning_path_id=_parse_uuid(learning_path_id)
    )
    prices = await paths_service.public_prices_for_paths(
        session, tenant_id=tenant.id, path_ids=[path.id]
    )
    return PublicPathDetailResponse(
        id=str(path.id),
        slug=path.slug,
        title=path.title,
        description=path.description,
        has_certificate=path.certificate_template_id is not None,
        courses=[
            PublicPathCourseRow(
                course_id=str(course.id),
                title=course.title,
                summary=course.summary,
                level=course.level,
                topic=course.topic,
                position=member.position,
            )
            for member, course in members
        ],
        price=_public_price(prices.get(path.id)),
    )


@router.get(
    "/path-enrolments",
    response_model=list[OwnPathEnrolmentResponse],
    summary="The caller's own learning-path enrolments",
)
async def list_own_path_enrolments(
    principal: PrincipalDep, session: SessionDep
) -> list[OwnPathEnrolmentResponse]:
    rows = await paths_service.list_own_path_enrolments(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return [
        OwnPathEnrolmentResponse(
            path_enrolment_id=str(row.path_enrolment_id),
            learning_path_id=str(row.learning_path_id),
            learning_path_title=row.learning_path_title,
            course_count=row.course_count,
            started_at=row.started_at,
            completed_at=row.completed_at,
            has_certificate=row.has_certificate,
        )
        for row in rows
    ]


@router.get(
    "/path-enrolments/{path_enrolment_id}/progress",
    response_model=PathProgressResponse,
    summary="Per-course progress rollup for one of the caller's path enrolments",
)
async def get_path_enrolment_progress(
    path_enrolment_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    crypto: CryptoDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> PathProgressResponse:
    progress = await paths_service.get_path_progress(
        session,
        crypto,
        storage,
        settings,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        path_enrolment_id=_parse_uuid(path_enrolment_id),
    )
    return PathProgressResponse(
        path_enrolment_id=str(progress.path_enrolment_id),
        learning_path_id=str(progress.learning_path_id),
        progress_percent=progress.progress_percent,
        completed_at=progress.completed_at,
        courses=[
            PathCourseProgressRow(
                course_id=str(c.course_id),
                course_title=c.course_title,
                enrolment_id=str(c.enrolment_id) if c.enrolment_id is not None else None,
                progress_percent=c.progress_percent,
                completed_at=c.completed_at,
            )
            for c in progress.courses
        ],
    )


__all__ = ["router"]
