from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.course import MANAGER_VISIBILITY_VALUES


class UpdateManagerVisibilityRequest(BaseModel):
    manager_visibility: str = Field(pattern="^(" + "|".join(MANAGER_VISIBILITY_VALUES) + ")$")


class CourseResponse(BaseModel):
    id: str
    title: str
    manager_visibility: str


class CoursesPageResponse(BaseModel):
    items: list[CourseResponse]


__all__ = ["CourseResponse", "CoursesPageResponse", "UpdateManagerVisibilityRequest"]
