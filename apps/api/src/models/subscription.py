"""Subscriptions (02 §6, REQ-PAY-12): recurring, multi-tier, course-bundle
access — additive to the one-time `Order -> Entitlement -> Enrolment` path
in `models/commerce.py`, not a replacement for it.

Renewals are funded through the *existing* EFT/PO manual-approval checkout
flow (`services/orders.py::_fulfil_order`), not automatic card charging —
Payfast/Netcash integration doesn't exist yet (`routers/orders.py`'s own
docstring). Each billing period is a real `Order` tagged with
`Order.subscription_id`; fulfilling it extends `Subscription.
current_period_end` and grants a fresh, time-bound `Entitlement` (via
`Entitlement.expires_at`, previously a dead column — see
`services/subscriptions.py`) for every course the effective plan bundles.

One `Subscription` row per (tenant, user) — reused across cancel/reactivate
cycles rather than spawning parallel historical rows, so the anti-abuse
cooldown (`last_plan_change_at`) has a single, unambiguous row to read.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

SUBSCRIPTION_STATUS_VALUES = ("pending", "active", "cancelled")

# create_type=False: the migration creates this Postgres enum type
# explicitly, once — same reasoning as commerce.py's OrderStatus.
SubscriptionStatus = Enum(
    *SUBSCRIPTION_STATUS_VALUES, name="subscription_status", create_type=False
)


class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plans"
    __table_args__ = (Index("uq_subscription_plans_tenant_slug", "tenant_id", "slug", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The sellable wrapper this plan is bought through — a Product with
    # kind="subscription", same "sellable vs learnable" split course
    # products already use (models/course.py's own docstring).
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # Immutable once set — Price rows are never mutated in this codebase
    # (services/orders.py resolves prices server-side, never trusts a
    # client-submitted amount); changing a plan's price means creating a
    # new Price and a new plan revision, not editing this row's price_id.
    price_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prices.id", ondelete="RESTRICT"), nullable=False
    )
    billing_interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class SubscriptionPlanCourse(Base, TimestampMixin):
    """A plan's course bundle. `course_id` points at the global `courses`
    table (models/course.py) — the bundle is tenant-specific (this row is),
    the course catalogue it draws from is not."""

    __tablename__ = "subscription_plan_courses"
    __table_args__ = (Index("uq_subscription_plan_courses", "plan_id", "course_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )


class Subscription(Base, TimestampMixin):
    """One row per learner, reused across cancel/reactivate cycles — never
    superseded by a new row, so `last_plan_change_at` (the anti-abuse
    cooldown anchor) always has exactly one place to read from."""

    __tablename__ = "subscriptions"
    __table_args__ = (Index("uq_subscriptions_tenant_user", "tenant_id", "user_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # A queued downgrade (02 §6 "downgrade at next cycle") — applied only
    # when the next period's Order is fulfilled, never immediately. Cleared
    # back to NULL once applied.
    pending_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        SubscriptionStatus, nullable=False, server_default="pending"
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Anti-abuse cooldown anchor (services/subscriptions.py::_cooldown_active)
    # — set on every call that changes plan_id (upgrade, queue-a-downgrade,
    # reactivate-after-cancel). Cancel/resume alone never touch this.
    last_plan_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "SUBSCRIPTION_STATUS_VALUES",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionPlanCourse",
    "SubscriptionStatus",
]
