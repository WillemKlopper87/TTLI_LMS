"""A narrow, single-field course-authoring surface (REQ-TEN-03).

No general course CRUD exists yet — content is still migration-seeded,
the same gap Phase 4's authoring UI left open. This is one field, added
for the same reason `POST /video-assets`/`POST /lessons/{id}/video`
were: a real capability sprint 2 needs (toggling
`courses.manager_visibility`) without inventing the general authoring
screen that isn't in scope here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import NotFound
from src.models.course import Course
from src.schemas.courses import CourseResponse, CoursesPageResponse, UpdateManagerVisibilityRequest

router = APIRouter(tags=["courses"])


@router.get("/courses", response_model=CoursesPageResponse)
async def list_courses(principal: PrincipalDep, session: SessionDep) -> CoursesPageResponse:
    principal.require("course:view")
    courses = (await session.execute(select(Course).order_by(Course.title))).scalars().all()
    return CoursesPageResponse(
        items=[
            CourseResponse(id=str(c.id), title=c.title, manager_visibility=c.manager_visibility)
            for c in courses
        ]
    )


@router.patch("/courses/{course_id}/manager-visibility", response_model=CourseResponse)
async def update_manager_visibility(
    course_id: str,
    body: UpdateManagerVisibilityRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> CourseResponse:
    principal.require("course:edit")
    try:
        course = await session.get(Course, uuid.UUID(course_id))
    except ValueError as exc:
        raise NotFound("No such course.") from exc
    if course is None:
        raise NotFound("No such course.")
    course.manager_visibility = body.manager_visibility
    await session.flush()
    return CourseResponse(
        id=str(course.id), title=course.title, manager_visibility=course.manager_visibility
    )


__all__ = ["router"]
