"""Model package.

Every model must be imported here. Alembic's autogenerate compares against
`Base.metadata`, and a model that is never imported is invisible to it — which
is how `alembic check` starts passing while the schema quietly drifts.
"""

from src.models.audit import AuditAction, AuditEvent
from src.models.auth import MagicLink, MfaRecoveryCode, PasswordReset, RefreshToken
from src.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin
from src.models.commerce import (
    Entitlement,
    Invoice,
    InvoiceItem,
    InvoiceNumberCounter,
    LedgerEntry,
    Order,
    OrderItem,
    Payment,
    Price,
    Product,
    TaxRule,
)
from src.models.consent import ConsentRecord
from src.models.contact import Contact
from src.models.event import Event
from src.models.lead import Lead
from src.models.rbac import Permission, Role, RoleAssignment, RolePermission
from src.models.tenant import Tenant, TenantDomain
from src.models.theme import TenantTheme
from src.models.user import User

__all__ = [
    "AuditAction",
    "AuditEvent",
    "Base",
    "ConsentRecord",
    "Contact",
    "Entitlement",
    "Event",
    "Invoice",
    "InvoiceItem",
    "InvoiceNumberCounter",
    "Lead",
    "LedgerEntry",
    "MagicLink",
    "MfaRecoveryCode",
    "Order",
    "OrderItem",
    "PasswordReset",
    "Payment",
    "Permission",
    "Price",
    "Product",
    "RefreshToken",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "SoftDeleteMixin",
    "TaxRule",
    "Tenant",
    "TenantDomain",
    "TenantMixin",
    "TenantTheme",
    "TimestampMixin",
    "User",
]
