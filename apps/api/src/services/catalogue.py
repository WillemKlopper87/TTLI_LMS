"""The product catalogue (02 §6.1, REQ-STORE-01) — public browsing plus
the admin authoring that makes a course sellable in the first place.

A product is sellable, a course is learnable, and `Product.course_id` is
the bridge between them (`services/orders.py::approve_eft` resolves it to
grant the entitlement and enrolment). Until frontend backlog item 5 there
was no way to *write* that bridge: `products`/`prices` were seeded by
migration only, so a freshly authored course could never be bought and the
storefront could only ever show the one demo product `0009` planted.

The authoring half below is `product:manage`-gated. That permission is
deliberately narrower than `subscription_plan:manage`, which `0002` also
grants to `content_author`: setting a price is a commercial decision, not
a content one, so `0022` grants `product:manage` to `admin`/`super_admin`
only. Don't widen it to match the other without deciding that explicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.commerce import OrderItem, Price, Product
from src.models.course import Course, CourseTenantAssignment
from src.models.subscription import SubscriptionPlanCourse


@dataclass(frozen=True, slots=True)
class PriceRow:
    id: uuid.UUID
    currency: str
    unit_amount: Decimal
    tax_behaviour: str


@dataclass(frozen=True, slots=True)
class ProductRow:
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    kind: str
    prices: list[PriceRow]
    subscription_plan_id: uuid.UUID | None
    bundled_courses: list[str] | None


async def list_active_products(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[ProductRow]:
    products = (
        (
            await session.execute(
                select(Product)
                .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
                .order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    if not products:
        return []

    product_ids = [p.id for p in products]
    prices = (
        (await session.execute(select(Price).where(Price.product_id.in_(product_ids))))
        .scalars()
        .all()
    )
    prices_by_product: dict[uuid.UUID, list[PriceRow]] = {}
    for price in prices:
        prices_by_product.setdefault(price.product_id, []).append(
            PriceRow(
                id=price.id,
                currency=price.currency,
                unit_amount=price.unit_amount,
                tax_behaviour=price.tax_behaviour,
            )
        )

    plan_ids = [p.subscription_plan_id for p in products if p.subscription_plan_id is not None]
    bundled_by_plan: dict[uuid.UUID, list[str]] = {}
    if plan_ids:
        rows = await session.execute(
            select(SubscriptionPlanCourse.plan_id, Course.title)
            .join(Course, Course.id == SubscriptionPlanCourse.course_id)
            .where(SubscriptionPlanCourse.plan_id.in_(plan_ids))
            .order_by(Course.title)
        )
        for plan_id, title in rows:
            bundled_by_plan.setdefault(plan_id, []).append(title)

    return [
        ProductRow(
            id=p.id,
            slug=p.slug,
            name=p.name,
            description=p.description,
            kind=p.kind,
            prices=prices_by_product.get(p.id, []),
            subscription_plan_id=p.subscription_plan_id,
            bundled_courses=(
                bundled_by_plan.get(p.subscription_plan_id, [])
                if p.subscription_plan_id is not None
                else None
            ),
        )
        for p in products
    ]


# ============================================ Admin: product authoring


class CatalogueError(AppError):
    """A refusal in product authoring — a duplicate slug, a course that
    isn't assigned to this tenant, or a price still referenced by a real
    order."""

    code = "CATALOGUE_REFUSED"


@dataclass(frozen=True, slots=True)
class AdminProductRow:
    """Unlike ProductRow this carries `is_active` and the course linkage —
    the storefront has no use for either, but the authoring screen cannot
    work without them."""

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    kind: str
    is_active: bool
    course_id: uuid.UUID | None
    course_title: str | None
    subscription_plan_id: uuid.UUID | None
    prices: list[PriceRow]


async def _assert_course_sellable(
    session: AsyncSession, *, tenant_id: uuid.UUID, course_id: uuid.UUID
) -> Course:
    """A tenant may only sell a course actually assigned to it.

    `courses` is global (02 §1.3) — every tenant can see the table — so the
    tenant scoping that matters lives in `course_tenant_assignments`.
    Without this check a tenant could attach any other tenant's course to
    its own product and sell access it was never granted.
    """
    course = (
        await session.execute(select(Course).where(Course.id == course_id))
    ).scalar_one_or_none()
    if course is None:
        raise NotFound("Course not found.")

    assigned = (
        await session.execute(
            select(CourseTenantAssignment.id).where(
                CourseTenantAssignment.tenant_id == tenant_id,
                CourseTenantAssignment.course_id == course_id,
            )
        )
    ).first()
    if assigned is None:
        raise CatalogueError("That course is not assigned to this tenant.")
    return course


async def create_product(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    name: str,
    description: str | None,
    course_id: uuid.UUID | None,
) -> Product:
    """Create a one-time-purchase product, optionally bound to a course.

    `kind` is always "course" here. Subscription products are created by
    `subscriptions.create_plan` instead, which owns the plan/product/price
    triple as one unit — creating one through this path would leave a
    subscription product with no plan behind it.
    """
    clash = (
        await session.execute(
            select(Product.id).where(Product.tenant_id == tenant_id, Product.slug == slug)
        )
    ).first()
    if clash is not None:
        raise CatalogueError(f"A product with the slug '{slug}' already exists.")

    if course_id is not None:
        await _assert_course_sellable(session, tenant_id=tenant_id, course_id=course_id)

    product = Product(
        id=uuid7(),
        tenant_id=tenant_id,
        slug=slug,
        name=name,
        description=description,
        kind="course",
        course_id=course_id,
        # Inactive on creation, deliberately: a product with no price yet
        # would otherwise appear in the public catalogue with nothing to
        # buy. Publishing is a second, explicit step once a price exists.
        is_active=False,
    )
    session.add(product)
    await session.flush()
    return product


async def update_product(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    name: str | None,
    description: str | None,
    course_id: uuid.UUID | None,
    is_active: bool | None,
) -> Product:
    product = await _get_own_product(session, tenant_id=tenant_id, product_id=product_id)

    if product.subscription_plan_id is not None:
        raise CatalogueError("This product belongs to a subscription plan — edit the plan instead.")

    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if course_id is not None:
        await _assert_course_sellable(session, tenant_id=tenant_id, course_id=course_id)
        product.course_id = course_id

    if is_active is True:
        # Refuse to publish a product nobody can actually buy. The
        # storefront renders a price list per product; an empty one is a
        # dead "Enrol" button, which reads as a broken site rather than an
        # unfinished one.
        has_price = (
            await session.execute(select(Price.id).where(Price.product_id == product.id))
        ).first()
        if has_price is None:
            raise CatalogueError("Add a price before making this product available to buy.")
        product.is_active = True
    elif is_active is False:
        product.is_active = False

    await session.flush()
    return product


async def add_price(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_id: uuid.UUID,
    currency: str,
    unit_amount: str,
    tax_behaviour: str,
) -> Price:
    product = await _get_own_product(session, tenant_id=tenant_id, product_id=product_id)
    price = Price(
        id=uuid7(),
        tenant_id=tenant_id,
        product_id=product.id,
        currency=currency,
        unit_amount=unit_amount,
        tax_behaviour=tax_behaviour,
    )
    session.add(price)
    await session.flush()
    return price


async def delete_price(session: AsyncSession, *, tenant_id: uuid.UUID, price_id: uuid.UUID) -> None:
    """Remove a price only while nothing has been bought at it.

    `order_items.price_id` is ON DELETE RESTRICT, so the database would
    refuse anyway — this check exists to turn that raw IntegrityError into
    an explanation, the same reason `0021`'s downgrade guards its own
    cleanup rather than letting the constraint fire.
    """
    price = (
        await session.execute(
            select(Price).where(Price.id == price_id, Price.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if price is None:
        raise NotFound("Price not found.")

    sold = (
        await session.execute(
            select(func.count()).select_from(OrderItem).where(OrderItem.price_id == price_id)
        )
    ).scalar_one()
    if sold:
        raise CatalogueError(
            "This price has already been used on an order and cannot be deleted. "
            "Deactivate the product instead."
        )

    await session.delete(price)
    await session.flush()


async def _get_own_product(
    session: AsyncSession, *, tenant_id: uuid.UUID, product_id: uuid.UUID
) -> Product:
    product = (
        await session.execute(
            select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFound("Product not found.")
    return product


async def list_all_products(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[AdminProductRow]:
    """Every product this tenant owns, active or not, with its course."""
    rows = (
        await session.execute(
            select(Product, Course.title)
            .outerjoin(Course, Course.id == Product.course_id)
            .where(Product.tenant_id == tenant_id)
            .order_by(Product.name)
        )
    ).all()
    if not rows:
        return []

    product_ids = [p.id for p, _ in rows]
    prices = (
        (await session.execute(select(Price).where(Price.product_id.in_(product_ids))))
        .scalars()
        .all()
    )
    prices_by_product: dict[uuid.UUID, list[PriceRow]] = {}
    for price in prices:
        prices_by_product.setdefault(price.product_id, []).append(
            PriceRow(
                id=price.id,
                currency=price.currency,
                unit_amount=price.unit_amount,
                tax_behaviour=price.tax_behaviour,
            )
        )

    return [
        AdminProductRow(
            id=p.id,
            slug=p.slug,
            name=p.name,
            description=p.description,
            kind=p.kind,
            is_active=p.is_active,
            course_id=p.course_id,
            course_title=title,
            subscription_plan_id=p.subscription_plan_id,
            prices=prices_by_product.get(p.id, []),
        )
        for p, title in rows
    ]


@dataclass(frozen=True, slots=True)
class SellableCourse:
    id: uuid.UUID
    title: str
    # Course.state, not "status" — the column is a ContentState
    # (draft/published/...), and the authoring screen shows it so nobody
    # prices a course that isn't published yet.
    state: str
    # The name of the product already selling this course, if any. Not a
    # hard block — a tenant may legitimately sell the same course twice
    # (different bundles or price points, exactly the shape 02 §6.1
    # describes) — but the authoring screen should say so rather than let
    # someone create an accidental duplicate.
    already_sold_as: str | None


async def list_sellable_courses(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[SellableCourse]:
    """Courses assigned to this tenant, and whether one is already sold.

    Scoped through `course_tenant_assignments` for the same reason
    `_assert_course_sellable` is: `courses` is global, so the assignment
    table is the only thing that makes "this tenant's courses" meaningful.
    """
    rows = (
        await session.execute(
            select(Course, Product.name)
            .join(CourseTenantAssignment, CourseTenantAssignment.course_id == Course.id)
            .outerjoin(
                Product,
                (Product.course_id == Course.id) & (Product.tenant_id == tenant_id),
            )
            .where(CourseTenantAssignment.tenant_id == tenant_id)
            .order_by(Course.title)
        )
    ).all()
    return [
        SellableCourse(
            id=course.id,
            title=course.title,
            state=course.state,
            already_sold_as=product_name,
        )
        for course, product_name in rows
    ]


__all__ = [
    "AdminProductRow",
    "CatalogueError",
    "PriceRow",
    "ProductRow",
    "SellableCourse",
    "add_price",
    "create_product",
    "delete_price",
    "list_active_products",
    "list_all_products",
    "list_sellable_courses",
    "update_product",
]
