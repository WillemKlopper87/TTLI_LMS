"""Partner portal services (2026-09-11-partner-portal-design.md).

Core operations:
  - Partner profile creation and activation
  - Client organisation management under a partner
  - Activation gate enforcement (MFA + agreement + registration for health pros)
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, Forbidden
from src.models.organisation import Organisation, OrganisationMember
from src.models.partner import PartnerProfile
from src.models.user import User


async def is_organisation_admin(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Whether user_id is an 'admin'-relationship member of organisation_id.

    Tenant-scoped: a membership row from another tenant never matches, since
    OrganisationMember.tenant_id is checked alongside organisation_id/user_id.
    """
    member = (
        await session.execute(
            select(OrganisationMember).where(
                OrganisationMember.tenant_id == tenant_id,
                OrganisationMember.organisation_id == organisation_id,
                OrganisationMember.user_id == user_id,
                OrganisationMember.relationship == "admin",
            )
        )
    ).scalar_one_or_none()
    return member is not None


async def require_organisation_admin(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    if not await is_organisation_admin(
        session, tenant_id=tenant_id, organisation_id=organisation_id, user_id=user_id
    ):
        raise Forbidden("You must be an admin of this organisation.")


async def create_partner_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
    display_name: str,
    bio: str | None = None,
    logo_object_key: str | None = None,
    professional_body: str | None = None,
) -> PartnerProfile:
    """Create a new partner profile for an organisation.

    Initial status is 'invited'; activation requires MFA enrollment,
    operator agreement acceptance, and (for health professionals)
    a registration number.

    Raises:
        AppError: If a partner profile already exists for this organisation.
    """
    existing = await get_partner_profile(
        session, tenant_id=tenant_id, organisation_id=organisation_id
    )
    if existing is not None:
        raise AppError("A partner profile already exists for this organisation")

    profile = PartnerProfile(
        tenant_id=tenant_id,
        organisation_id=organisation_id,
        display_name=display_name,
        bio=bio,
        logo_object_key=logo_object_key,
        professional_body=professional_body,
        status="invited",
    )
    session.add(profile)
    await session.flush()
    return profile


async def get_partner_profile(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    organisation_id: uuid.UUID,
) -> PartnerProfile | None:
    """Retrieve a partner profile by organisation."""
    return (
        await session.execute(
            select(PartnerProfile).where(
                PartnerProfile.tenant_id == tenant_id,
                PartnerProfile.organisation_id == organisation_id,
            )
        )
    ).scalar_one_or_none()


def can_activate_partner(profile: PartnerProfile, user: User) -> bool:
    """Check if a partner profile can be activated.

    Activation requires:
      1. Operator agreement accepted (operator_agreement_accepted_at is not None)
      2. MFA enrolled (user.mfa_secret_encrypted is not None)
      3. For health professionals: registration_number_encrypted is not None

    Args:
        profile: The partner profile to check
        user: The user who will activate (must have MFA enrolled)

    Returns:
        True if all gates are cleared, False otherwise.
    """
    # Gate 1: Operator agreement must be accepted
    if profile.operator_agreement_accepted_at is None:
        return False

    # Gate 2: MFA must be enrolled (check user's MFA secret)
    if user.mfa_secret_encrypted is None:
        return False

    # Gate 3: For health professionals, registration number is required
    if profile.professional_body is not None:
        if profile.registration_number_encrypted is None:
            return False

    return True


async def activate_partner(
    session: AsyncSession,
    *,
    profile: PartnerProfile,
    user: User,
) -> None:
    """Activate a partner profile if all gates are cleared.

    Raises AppError if activation gates are not met.
    """
    if not can_activate_partner(profile, user):
        missing_gates = []
        if profile.operator_agreement_accepted_at is None:
            missing_gates.append("operator agreement not accepted")
        if user.mfa_secret_encrypted is None:
            missing_gates.append("MFA not enrolled")
        if profile.professional_body is not None and profile.registration_number_encrypted is None:
            missing_gates.append("registration number required for health professionals")
        raise AppError(
            "Cannot activate partner: required gates not met",
            {"missing_gates": missing_gates},
        )

    profile.status = "active"
    await session.flush()


async def get_admin_partner_organisation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Organisation | None:
    """The partner-kind organisation the caller administers, if any.

    Used to resolve the parent for client-org creation instead of trusting
    a client-supplied organisation id.
    """
    return (
        await session.execute(
            select(Organisation)
            .join(
                OrganisationMember,
                OrganisationMember.organisation_id == Organisation.id,
            )
            .where(
                Organisation.tenant_id == tenant_id,
                Organisation.kind == "partner",
                OrganisationMember.tenant_id == tenant_id,
                OrganisationMember.user_id == user_id,
                OrganisationMember.relationship == "admin",
            )
        )
    ).scalars().first()


async def create_client_organisation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    parent_organisation_id: uuid.UUID,
    name: str,
) -> Organisation:
    """Create a client organisation under a partner.

    A client organisation is linked to its partner via parent_organisation_id
    and has kind='client'. The partner's org admins are admins of clients
    for assessment purposes only, not for seats, billing, or CRM.

    Args:
        session: Database session
        tenant_id: Tenant ID (must match parent)
        parent_organisation_id: Partner organisation ID
        name: Client organisation name

    Returns:
        Newly created Organisation with kind='client'

    Raises:
        AppError if parent is not a partner or does not exist
    """
    # Verify parent exists and is a partner
    parent = (
        await session.execute(
            select(Organisation).where(
                Organisation.tenant_id == tenant_id,
                Organisation.id == parent_organisation_id,
            )
        )
    ).scalar_one_or_none()

    if parent is None:
        raise AppError("Parent organisation not found")
    if parent.kind != "partner":
        raise AppError("Parent must be a partner organisation", {"kind": parent.kind})

    client = Organisation(
        tenant_id=tenant_id,
        name=name,
        kind="client",
        parent_organisation_id=parent_organisation_id,
    )
    session.add(client)
    await session.flush()
    return client


async def get_partner_clients(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    partner_id: uuid.UUID,
) -> list[Organisation]:
    """List all client organisations under a partner.

    Returns organisations with kind='client' and parent_organisation_id=partner_id.
    """
    result = await session.execute(
        select(Organisation).where(
            Organisation.tenant_id == tenant_id,
            Organisation.kind == "client",
            Organisation.parent_organisation_id == partner_id,
        )
    )
    return list(result.scalars().all())


__all__ = [
    "activate_partner",
    "can_activate_partner",
    "create_client_organisation",
    "create_partner_profile",
    "get_admin_partner_organisation",
    "get_partner_clients",
    "get_partner_profile",
    "is_organisation_admin",
    "require_organisation_admin",
]
