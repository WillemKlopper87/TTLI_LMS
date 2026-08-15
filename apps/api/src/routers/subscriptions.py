"""Multi-tier subscriptions (02 §6, REQ-PAY-12).

Learner self-service (subscribe/change-plan/cancel/resume/renew) is gated
on the caller owning the subscription — the same ownership discipline
`routers/orders.py` uses for orders, not an admin action. Plan authoring
(`subscription_plan:manage`) is a content-author/admin action, same split
`routers/courses.py` draws between `course:view` (learner-adjacent) and
`course:edit` (authoring).

Every learner-facing endpoint here that funds a period creates the actual
`Order` itself, right after `services/subscriptions.py`'s prepare_* helper
validates state — that two-step "prepare in the service, create the order
in the router" split exists because `services/subscriptions.py` never
imports `services/orders.py` (its own module docstring explains why).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.config import Settings
from src.core.deps import PrincipalDep, SessionDep, SettingsDep
from src.core.errors import AppError, NotFound
from src.models.subscription import Subscription, SubscriptionPlan
from src.schemas.subscriptions import (
    ChangePlanRequest,
    PlanCourseRequest,
    PlanCourseRow,
    PlanCoursesPageResponse,
    RenewRequest,
    SubscribeRequest,
    SubscriptionOrderResponse,
    SubscriptionPlanCreateRequest,
    SubscriptionPlanResponse,
    SubscriptionPlansPageResponse,
    SubscriptionPlanUpdateRequest,
    SubscriptionResponse,
)
from src.services import orders as orders_service
from src.services import subscriptions as subscriptions_service

router = APIRouter(tags=["subscriptions"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotFound("No such resource.") from exc


def _plan_response(plan: SubscriptionPlan) -> SubscriptionPlanResponse:
    return SubscriptionPlanResponse(
        id=str(plan.id),
        slug=plan.slug,
        name=plan.name,
        description=plan.description,
        price_id=str(plan.price_id),
        billing_interval_days=plan.billing_interval_days,
        is_active=plan.is_active,
    )


def _subscription_response(subscription: Subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=str(subscription.id),
        plan_id=str(subscription.plan_id),
        pending_plan_id=str(subscription.pending_plan_id) if subscription.pending_plan_id else None,
        status=subscription.status,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


def _require_subscriptions_enabled(settings: Settings) -> None:
    if not settings.subscriptions_enabled:
        raise AppError("Subscriptions are not currently available.")


# ==================================================== Admin: plan authoring


@router.post(
    "/subscription-plans",
    response_model=SubscriptionPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription_plan(
    body: SubscriptionPlanCreateRequest, principal: PrincipalDep, session: SessionDep
) -> SubscriptionPlanResponse:
    principal.require("subscription_plan:manage")
    plan = await subscriptions_service.create_plan(
        session,
        tenant_id=principal.tenant_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        currency=body.currency.upper(),
        unit_amount=str(body.unit_amount),
        tax_behaviour=body.tax_behaviour,
        billing_interval_days=body.billing_interval_days,
    )
    return _plan_response(plan)


@router.get("/subscription-plans", response_model=SubscriptionPlansPageResponse)
async def list_subscription_plans(
    principal: PrincipalDep, session: SessionDep
) -> SubscriptionPlansPageResponse:
    principal.require("subscription_plan:manage")
    plans = await subscriptions_service.list_plans(session, tenant_id=principal.tenant_id)
    return SubscriptionPlansPageResponse(items=[_plan_response(p) for p in plans])


@router.patch("/subscription-plans/{plan_id}", response_model=SubscriptionPlanResponse)
async def update_subscription_plan(
    plan_id: str, body: SubscriptionPlanUpdateRequest, principal: PrincipalDep, session: SessionDep
) -> SubscriptionPlanResponse:
    principal.require("subscription_plan:manage")
    plan = await subscriptions_service.update_plan(
        session,
        tenant_id=principal.tenant_id,
        plan_id=_parse_uuid(plan_id),
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    return _plan_response(plan)


@router.post(
    "/subscription-plans/{plan_id}/courses",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def add_course_to_plan(
    plan_id: str, body: PlanCourseRequest, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("subscription_plan:manage")
    await subscriptions_service.add_course_to_plan(
        session,
        tenant_id=principal.tenant_id,
        plan_id=_parse_uuid(plan_id),
        course_id=_parse_uuid(body.course_id),
    )


@router.delete(
    "/subscription-plans/{plan_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def remove_course_from_plan(
    plan_id: str, course_id: str, principal: PrincipalDep, session: SessionDep
) -> None:
    principal.require("subscription_plan:manage")
    await subscriptions_service.remove_course_from_plan(
        session,
        tenant_id=principal.tenant_id,
        plan_id=_parse_uuid(plan_id),
        course_id=_parse_uuid(course_id),
    )


@router.get("/subscription-plans/{plan_id}/courses", response_model=PlanCoursesPageResponse)
async def list_plan_courses(
    plan_id: str, principal: PrincipalDep, session: SessionDep
) -> PlanCoursesPageResponse:
    principal.require("subscription_plan:manage")
    courses = await subscriptions_service.list_plan_courses(
        session, tenant_id=principal.tenant_id, plan_id=_parse_uuid(plan_id)
    )
    return PlanCoursesPageResponse(
        items=[PlanCourseRow(course_id=str(c.id), course_title=c.title) for c in courses]
    )


# ===================================================== Learner self-service


@router.post(
    "/subscriptions", response_model=SubscriptionOrderResponse, status_code=status.HTTP_201_CREATED
)
async def subscribe(
    body: SubscribeRequest, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> SubscriptionOrderResponse:
    _require_subscriptions_enabled(settings)
    subscription, plan = await subscriptions_service.prepare_subscribe(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        plan_id=_parse_uuid(body.plan_id),
    )
    order = await orders_service.create_order(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        currency=body.currency.upper(),
        customer_type=body.customer_type,
        lines=[orders_service.OrderLineRequest(price_id=plan.price_id, quantity=1)],
        subscription_id=subscription.id,
    )
    return SubscriptionOrderResponse(
        subscription=_subscription_response(subscription), order_id=str(order.id)
    )


@router.get("/subscriptions/me", response_model=SubscriptionResponse)
async def get_own_subscription(
    principal: PrincipalDep, session: SessionDep
) -> SubscriptionResponse:
    subscription = await subscriptions_service.get_own_subscription(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    if subscription is None:
        raise NotFound("No subscription.")
    return _subscription_response(subscription)


@router.post("/subscriptions/me/change-plan", response_model=SubscriptionOrderResponse)
async def change_plan(
    body: ChangePlanRequest, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> SubscriptionOrderResponse:
    _require_subscriptions_enabled(settings)
    subscription, plan, is_upgrade = await subscriptions_service.prepare_change_plan(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        new_plan_id=_parse_uuid(body.plan_id),
    )
    if not is_upgrade:
        # Downgrade — deferred to the next renewal, no order created now.
        return SubscriptionOrderResponse(
            subscription=_subscription_response(subscription), order_id=None
        )
    order = await orders_service.create_order(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        currency=body.currency.upper(),
        customer_type=body.customer_type,
        lines=[orders_service.OrderLineRequest(price_id=plan.price_id, quantity=1)],
        subscription_id=subscription.id,
    )
    return SubscriptionOrderResponse(
        subscription=_subscription_response(subscription), order_id=str(order.id)
    )


@router.post("/subscriptions/me/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(principal: PrincipalDep, session: SessionDep) -> SubscriptionResponse:
    subscription = await subscriptions_service.cancel(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return _subscription_response(subscription)


@router.post("/subscriptions/me/resume", response_model=SubscriptionResponse)
async def resume_subscription(principal: PrincipalDep, session: SessionDep) -> SubscriptionResponse:
    subscription = await subscriptions_service.resume(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return _subscription_response(subscription)


@router.post("/subscriptions/me/renew", response_model=SubscriptionOrderResponse)
async def renew_subscription(
    body: RenewRequest, principal: PrincipalDep, session: SessionDep, settings: SettingsDep
) -> SubscriptionOrderResponse:
    _require_subscriptions_enabled(settings)
    subscription, plan = await subscriptions_service.prepare_renewal(
        session, tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    order = await orders_service.create_order(
        session,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        currency=body.currency.upper(),
        customer_type=body.customer_type,
        lines=[orders_service.OrderLineRequest(price_id=plan.price_id, quantity=1)],
        subscription_id=subscription.id,
    )
    return SubscriptionOrderResponse(
        subscription=_subscription_response(subscription), order_id=str(order.id)
    )


__all__ = ["router"]
