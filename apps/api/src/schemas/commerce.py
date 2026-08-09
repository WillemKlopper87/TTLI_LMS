from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# REQ-PAY-08 / 02 §6.5's three customer types.
CUSTOMER_TYPES = ("individual", "registered_business", "international")


class OrderLine(BaseModel):
    price_id: str
    quantity: int = Field(default=1, ge=1, le=20)


class CreateOrderRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    customer_type: str
    lines: list[OrderLine] = Field(min_length=1, max_length=20)


class OrderItemResponse(BaseModel):
    product_id: str
    quantity: int
    unit_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal


class OrderResponse(BaseModel):
    id: str
    status: str
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    payment_reference: str | None
    items: list[OrderItemResponse]


class EftCheckoutResponse(BaseModel):
    payment_id: str
    payment_reference: str
    bank_name: str
    account_name: str
    account_number: str
    branch_code: str
    amount: Decimal
    currency: str


class RejectPaymentRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class InvoiceResponse(BaseModel):
    id: str
    number: str
    status: str
    issued_at: datetime
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal


__all__ = [
    "CUSTOMER_TYPES",
    "CreateOrderRequest",
    "EftCheckoutResponse",
    "InvoiceResponse",
    "OrderItemResponse",
    "OrderLine",
    "OrderResponse",
    "RejectPaymentRequest",
]
