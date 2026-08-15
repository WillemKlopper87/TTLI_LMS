from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SubscriptionPlanCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern="^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    unit_amount: Decimal = Field(gt=0)
    tax_behaviour: str = Field(default="exclusive", pattern="^(exclusive|inclusive)$")
    billing_interval_days: int = Field(default=30, ge=1)


class SubscriptionPlanUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SubscriptionPlanResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    price_id: str
    billing_interval_days: int
    is_active: bool


class SubscriptionPlansPageResponse(BaseModel):
    items: list[SubscriptionPlanResponse]


class PlanCourseRequest(BaseModel):
    course_id: str


class PlanCourseRow(BaseModel):
    course_id: str
    course_title: str


class PlanCoursesPageResponse(BaseModel):
    items: list[PlanCourseRow]


class SubscribeRequest(BaseModel):
    plan_id: str
    currency: str = Field(min_length=3, max_length=3)
    customer_type: str


class ChangePlanRequest(BaseModel):
    plan_id: str
    currency: str = Field(min_length=3, max_length=3)
    customer_type: str


class RenewRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    customer_type: str


class SubscriptionResponse(BaseModel):
    id: str
    plan_id: str
    pending_plan_id: str | None
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


class SubscriptionOrderResponse(BaseModel):
    """Returned instead of / alongside `SubscriptionResponse` when the call
    created a real `Order` that still needs EFT/PO checkout — `order_id`
    is `None` for a queued downgrade, which creates no order at all
    (applied only when the next renewal is fulfilled)."""

    subscription: SubscriptionResponse
    order_id: str | None


__all__ = [
    "ChangePlanRequest",
    "PlanCourseRequest",
    "PlanCourseRow",
    "PlanCoursesPageResponse",
    "RenewRequest",
    "SubscribeRequest",
    "SubscriptionOrderResponse",
    "SubscriptionPlanCreateRequest",
    "SubscriptionPlanResponse",
    "SubscriptionPlanUpdateRequest",
    "SubscriptionPlansPageResponse",
    "SubscriptionResponse",
]
