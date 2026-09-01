"""Per-tenant feature kill switches (docs/research/devsecops-deployment.md
§5.3's recommendation, finally wired up). Extends `Tenant.feature_flags`,
a JSONB column that has existed since the baseline migration
(0001_baseline_schema.py) with nothing reading or writing it until now.

Semantics: a flag defaults ON. The stored JSONB only ever needs an entry
for a flag someone has turned OFF — an empty `{}` means everything is
enabled, so a brand-new tenant behaves correctly without an admin having
to visit a settings screen first. This is a kill switch, not a staged
rollout: percentage-based/cohort assignment is explicitly left for
whenever real A/B experimentation is a requirement
(devsecops-deployment.md §5.2), not before.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.models.tenant import Tenant


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    key: str
    label: str
    description: str


# The catalogue of flags an admin can see and toggle. Adding one is
# exactly this — a tuple entry — never a migration, since every flag
# shares the same JSONB column.
KNOWN_FLAGS: tuple[FeatureFlag, ...] = (
    FeatureFlag(
        key="subscriptions",
        label="Subscriptions",
        description=(
            "Learner self-service subscribe / change-plan / cancel / renew. "
            "Existing subscriptions keep running; new subscribe attempts are "
            "refused while off. Layers on top of the deployment-wide "
            "SUBSCRIPTIONS_ENABLED env var — both must be on."
        ),
    ),
    FeatureFlag(
        key="workshops",
        label="Live workshops",
        description=(
            "Booking a live workshop session. Existing bookings are "
            "unaffected; new bookings are refused while off."
        ),
    ),
    FeatureFlag(
        key="podcasts",
        label="Podcasts",
        description="The public podcast listing and episode pages.",
    ),
)

_KNOWN_KEYS = frozenset(f.key for f in KNOWN_FLAGS)


async def get_flags(session: AsyncSession, *, tenant_id: UUID) -> dict[str, bool]:
    """Every known flag's current state for this tenant. Always complete
    (one entry per KNOWN_FLAGS) even for a tenant whose stored JSONB has
    never been touched — absence means enabled."""
    tenant = await session.get(Tenant, tenant_id)
    stored = tenant.feature_flags if tenant else {}
    return {flag.key: bool(stored.get(flag.key, True)) for flag in KNOWN_FLAGS}


async def is_enabled(session: AsyncSession, *, tenant_id: UUID, flag: str) -> bool:
    """The one call site actually gating a feature needs. Fails open (True)
    for an unknown tenant rather than 500ing a request over a flag lookup —
    the tenant-resolution middleware is what's responsible for refusing an
    unknown tenant, not this."""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return True
    return bool(tenant.feature_flags.get(flag, True))


async def set_flag(
    session: AsyncSession, *, tenant_id: UUID, flag: str, enabled: bool
) -> dict[str, bool]:
    if flag not in _KNOWN_KEYS:
        raise AppError(f"Unknown feature flag: {flag}")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("Tenant not found.")
    # A new dict, not an in-place mutation of tenant.feature_flags —
    # SQLAlchemy's change tracking on a JSONB column does not notice an
    # in-place dict mutation as something to flush; only assigning a new
    # object trips it, the same rule every mutable-JSON column needs.
    updated = dict(tenant.feature_flags)
    updated[flag] = enabled
    tenant.feature_flags = updated
    await session.flush()
    return await get_flags(session, tenant_id=tenant_id)


__all__ = ["KNOWN_FLAGS", "FeatureFlag", "get_flags", "is_enabled", "set_flag"]
