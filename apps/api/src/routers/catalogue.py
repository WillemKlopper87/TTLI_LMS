"""Admin product authoring — making an authored course purchasable
(frontend backlog item 5).

Sits on `/catalogue/*` rather than extending `GET /products`, which is
public and unauthenticated: an admin needs to see *inactive* products too,
and widening the public endpoint with an `include_inactive` flag would
mean one route serving two authorisation levels — the kind of split that
eventually leaks. Keeping the write side on its own prefix leaves the
storefront contract untouched.

Everything here is `product:manage`-gated. See `services/catalogue.py`'s
module docstring for why that permission is narrower than
`subscription_plan:manage`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import PrincipalDep, SessionDep
from src.core.errors import AppError
from src.models.commerce import Price, Product
from src.schemas.catalogue import (
    AdminPriceRow,
    AdminProductResponse,
    AdminProductsPage,
    PriceCreateRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
    SellableCourseRow,
    SellableCoursesPage,
)
from src.services import catalogue as catalogue_service

router = APIRouter(prefix="/catalogue", tags=["catalogue"])


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AppError("Not a valid identifier.") from exc


def _row_response(row: catalogue_service.AdminProductRow) -> AdminProductResponse:
    return AdminProductResponse(
        id=str(row.id),
        slug=row.slug,
        name=row.name,
        description=row.description,
        kind=row.kind,
        is_active=row.is_active,
        course_id=str(row.course_id) if row.course_id is not None else None,
        course_title=row.course_title,
        subscription_plan_id=(
            str(row.subscription_plan_id) if row.subscription_plan_id is not None else None
        ),
        prices=[
            AdminPriceRow(
                id=str(p.id),
                currency=p.currency,
                unit_amount=p.unit_amount,
                tax_behaviour=p.tax_behaviour,
            )
            for p in row.prices
        ],
    )


def _product_response(product: Product, course_title: str | None = None) -> AdminProductResponse:
    """For the single-object create/update replies, which have no prices
    joined yet — the list endpoint is what carries the full picture."""
    return AdminProductResponse(
        id=str(product.id),
        slug=product.slug,
        name=product.name,
        description=product.description,
        kind=product.kind,
        is_active=product.is_active,
        course_id=str(product.course_id) if product.course_id is not None else None,
        course_title=course_title,
        subscription_plan_id=(
            str(product.subscription_plan_id) if product.subscription_plan_id is not None else None
        ),
        prices=[],
    )


@router.get("/products", response_model=AdminProductsPage)
async def list_products_for_admin(
    principal: PrincipalDep, session: SessionDep
) -> AdminProductsPage:
    principal.require("product:manage")
    rows = await catalogue_service.list_all_products(session, tenant_id=principal.tenant_id)
    return AdminProductsPage(items=[_row_response(r) for r in rows])


@router.get("/sellable-courses", response_model=SellableCoursesPage)
async def list_sellable_courses(
    principal: PrincipalDep, session: SessionDep
) -> SellableCoursesPage:
    principal.require("product:manage")
    courses = await catalogue_service.list_sellable_courses(session, tenant_id=principal.tenant_id)
    return SellableCoursesPage(
        items=[
            SellableCourseRow(
                id=str(c.id),
                title=c.title,
                state=c.state,
                already_sold_as=c.already_sold_as,
            )
            for c in courses
        ]
    )


@router.post("/products", response_model=AdminProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreateRequest, principal: PrincipalDep, session: SessionDep
) -> AdminProductResponse:
    principal.require("product:manage")
    product = await catalogue_service.create_product(
        session,
        tenant_id=principal.tenant_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        course_id=_parse_uuid(body.course_id) if body.course_id else None,
    )
    return _product_response(product)


@router.patch("/products/{product_id}", response_model=AdminProductResponse)
async def update_product(
    product_id: str,
    body: ProductUpdateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> AdminProductResponse:
    principal.require("product:manage")
    product = await catalogue_service.update_product(
        session,
        tenant_id=principal.tenant_id,
        product_id=_parse_uuid(product_id),
        name=body.name,
        description=body.description,
        course_id=_parse_uuid(body.course_id) if body.course_id else None,
        is_active=body.is_active,
    )
    return _product_response(product)


@router.post(
    "/products/{product_id}/prices",
    response_model=AdminPriceRow,
    status_code=status.HTTP_201_CREATED,
)
async def add_price(
    product_id: str,
    body: PriceCreateRequest,
    principal: PrincipalDep,
    session: SessionDep,
) -> AdminPriceRow:
    principal.require("product:manage")
    price: Price = await catalogue_service.add_price(
        session,
        tenant_id=principal.tenant_id,
        product_id=_parse_uuid(product_id),
        currency=body.currency.upper(),
        unit_amount=str(body.unit_amount),
        tax_behaviour=body.tax_behaviour,
    )
    return AdminPriceRow(
        id=str(price.id),
        currency=price.currency,
        unit_amount=price.unit_amount,
        tax_behaviour=price.tax_behaviour,
    )


@router.delete("/prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_price(price_id: str, principal: PrincipalDep, session: SessionDep) -> None:
    principal.require("product:manage")
    await catalogue_service.delete_price(
        session, tenant_id=principal.tenant_id, price_id=_parse_uuid(price_id)
    )
