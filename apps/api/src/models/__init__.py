"""Model package.

Every model must be imported here. Alembic's autogenerate compares against
`Base.metadata`, and a model that is never imported is invisible to it — which
is how `alembic check` starts passing while the schema quietly drifts.
"""

from src.models.audit import AuditAction, AuditEvent
from src.models.auth import MagicLink, MfaRecoveryCode, RefreshToken
from src.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin
from src.models.event import Event
from src.models.rbac import Permission, Role, RoleAssignment, RolePermission
from src.models.tenant import Tenant, TenantDomain
from src.models.user import User

__all__ = [
    "AuditAction",
    "AuditEvent",
    "Base",
    "Event",
    "MagicLink",
    "MfaRecoveryCode",
    "Permission",
    "RefreshToken",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "SoftDeleteMixin",
    "Tenant",
    "TenantDomain",
    "TenantMixin",
    "TimestampMixin",
    "User",
]
