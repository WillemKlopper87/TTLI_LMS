"""Facilitator licensing service and RLS isolation tests.

Service-level tests pin the invariants: licence creation, seat grant validation,
RLS isolation between licensees, and active-licence queries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from src.core.errors import AppError
from src.models.licence import Licence
from src.models.organisation import Organisation
from src.models.user import User
from src.services import licence as licence_service

pytestmark = pytest.mark.integration


async def _demo_tenant_id(tenant_session_factory):  # type: ignore[no-untyped-def]
    import sqlalchemy as sa

    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _make_organisation(session, *, tenant_id: uuid.UUID, name: str) -> Organisation:
    # kind='licensee': create_licence requires it (services/licence.py) —
    # every organisation this test file creates exists to be licensed.
    org = Organisation(
        tenant_id=tenant_id,
        name=name,
        kind="licensee",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_user(session, *, tenant_id: uuid.UUID, email: str) -> User:
    # email_blind_index must actually vary with `email` — a hardcoded
    # value here made uq_users_tenant_email collide on the second call
    # regardless of what different `email` a caller passed, since that's
    # the column the constraint actually checks.
    import hashlib

    user = User(
        tenant_id=tenant_id,
        email_encrypted=email.encode(),
        email_blind_index=hashlib.sha256(email.encode()).digest(),
        email_domain=email.split("@", 1)[-1],
    )
    session.add(user)
    await session.flush()
    return user


async def _make_course(session, *, tenant_id: uuid.UUID, title: str) -> tuple[uuid.UUID, str]:
    """Create a course and return (course_id, course_id_str) for testing.

    courses has no tenant_id column — courses are deliberately global,
    not tenant-scoped (see Course model's own docstring); tenant_id here
    is only used as created_by_tenant_id, and only for provenance, not
    visibility. licence.create_licence never validates course_id against
    course_tenant_assignments, so a bare row satisfying the FK is enough.
    """
    import sqlalchemy as sa

    course_id = uuid.uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO courses
            (id, slug, title, description, state, created_by_tenant_id, created_at, updated_at)
            VALUES (:id, :slug, :title, :desc, 'published', :tenant_id, now(), now())
            """
        ),
        {
            "id": course_id,
            "slug": f"test-course-{course_id.hex[:8]}",
            "title": title,
            "desc": "Test course",
            "tenant_id": tenant_id,
        },
    )
    await session.flush()
    return course_id, str(course_id)


async def test_create_licence_with_course(tenant_session_factory):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
            price_per_seat_cents=9999,
            currency="ZAR",
        )

        assert licence.organisation_id == org.id
        assert licence.course_id == course_id
        assert licence.learning_path_id is None
        assert licence.status == "active"
        assert licence.seats_purchased == 10
        assert licence.seats_used == 0


async def test_create_licence_rejects_neither_course_nor_path(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        with pytest.raises(AppError, match="must target either a course or a learning path"):
            await licence_service.create_licence(
                session,
                tenant_id=tenant_id,
                organisation_id=org.id,
                course_id=None,
                learning_path_id=None,
                seats_purchased=10,
                starts_at=starts_at,
                ends_at=ends_at,
            )


async def test_create_licence_rejects_both_course_and_path(tenant_session_factory):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        with pytest.raises(AppError, match="must target either a course or a learning path"):
            await licence_service.create_licence(
                session,
                tenant_id=tenant_id,
                organisation_id=org.id,
                course_id=course_id,
                learning_path_id=uuid.uuid4(),
                seats_purchased=10,
                starts_at=starts_at,
                ends_at=ends_at,
            )


async def test_create_licence_rejects_end_before_start(tenant_session_factory):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")

        starts_at = datetime.now(UTC)
        ends_at = starts_at - timedelta(days=1)

        with pytest.raises(AppError, match="must start before it ends"):
            await licence_service.create_licence(
                session,
                tenant_id=tenant_id,
                organisation_id=org.id,
                course_id=course_id,
                seats_purchased=10,
                starts_at=starts_at,
                ends_at=ends_at,
            )


async def test_grant_seat_succeeds_and_increments_seats_used(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        grant = await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner.id,
        )

        assert grant.licence_id == licence.id
        assert grant.learner_user_id == learner.id
        assert grant.revoked_at is None

        # Refetch licence to see updated seats_used
        licence_refetched = await session.get(Licence, licence.id)
        assert licence_refetched is not None
        assert licence_refetched.seats_used == 1


async def test_grant_seat_rejects_when_no_seats_available(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner1 = await _make_user(session, tenant_id=tenant_id, email="learner1@example.com")
        learner2 = await _make_user(session, tenant_id=tenant_id, email="learner2@example.com")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=1,  # Only 1 seat
            starts_at=starts_at,
            ends_at=ends_at,
        )

        # First grant succeeds
        await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner1.id,
        )

        # Second grant fails
        with pytest.raises(AppError, match="No seats available"):
            await licence_service.grant_seat(
                session,
                tenant_id=tenant_id,
                licence_id=licence.id,
                learner_user_id=learner2.id,
            )


async def test_grant_seat_rejects_outside_validity_window(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        now = datetime.now(UTC)
        # Licence expired yesterday
        starts_at = now - timedelta(days=2)
        ends_at = now - timedelta(days=1)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        with pytest.raises(AppError, match="outside its validity window"):
            await licence_service.grant_seat(
                session,
                tenant_id=tenant_id,
                licence_id=licence.id,
                learner_user_id=learner.id,
            )


async def test_has_active_licence_returns_true_for_valid_grant(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner.id,
        )

        has_lic = await licence_service.has_active_licence(
            session,
            tenant_id=tenant_id,
            learner_user_id=learner.id,
            course_id=course_id,
        )
        assert has_lic is True


async def test_has_active_licence_returns_false_for_revoked_grant(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        grant = await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner.id,
        )

        # Revoke the seat
        await licence_service.revoke_seat(session, tenant_id=tenant_id, grant_id=grant.id)

        has_lic = await licence_service.has_active_licence(
            session,
            tenant_id=tenant_id,
            learner_user_id=learner.id,
            course_id=course_id,
        )
        assert has_lic is False


async def test_rls_isolates_licences_between_tenants(tenant_session_factory):  # type: ignore[no-untyped-def]
    """RLS policy ensures one tenant's licences are invisible to another."""
    import sqlalchemy as sa

    tenant_id = await _demo_tenant_id(tenant_session_factory)

    # Create licence in demo tenant
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Demo Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Demo Course")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        licence_id = licence.id

    # A session with no tenant context sets app.tenant_id to '' (core/db.py::
    # set_tenant), which the RLS policy's `tenant_id = NULLIF(..., '')::uuid`
    # normalises to NULL — matching no row's tenant_id, ever. The previous
    # version of this test asserted the opposite (row is not None), which
    # can only pass if RLS is failing to isolate tenants; this was never
    # actually run against real Postgres before now.
    async with tenant_session_factory(None) as session:
        row = (
            await session.execute(
                sa.text("SELECT id FROM licences WHERE id = :id"),
                {"id": licence_id},
            )
        ).first()
        assert row is None, "RLS should hide the licence from a session with no tenant context"


async def test_create_licence_rejects_non_licensee_organisation(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    """kind='licensee' is required — an ordinary (kind='standard')
    organisation cannot be licensed."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = Organisation(tenant_id=tenant_id, name="Ordinary Org")  # kind defaults to 'standard'
        session.add(org)
        await session.flush()
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        with pytest.raises(AppError, match="licensee organisation"):
            await licence_service.create_licence(
                session,
                tenant_id=tenant_id,
                organisation_id=org.id,
                course_id=course_id,
                seats_purchased=10,
                starts_at=starts_at,
                ends_at=ends_at,
            )


async def test_grant_seat_provisions_real_course_entitlement_and_enrolment(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    """grant_seat must produce actual course access, not just a billing
    record — a real Entitlement plus Enrolment, the same shape
    services/organisations.py::assign_seat grants for corporate seats."""
    import sqlalchemy as sa
    from src.models.commerce import Entitlement
    from src.models.learning import Enrolment

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=10,
            starts_at=starts_at,
            ends_at=ends_at,
        )

        grant = await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner.id,
        )

        assert grant.entitlement_id is not None
        entitlement = await session.get(Entitlement, grant.entitlement_id)
        assert entitlement is not None
        assert entitlement.user_id == learner.id
        assert entitlement.kind == "course"
        assert entitlement.target_id == course_id
        assert entitlement.organisation_id == org.id

        enrolment = (
            await session.execute(
                sa.select(Enrolment).where(
                    Enrolment.tenant_id == tenant_id,
                    Enrolment.user_id == learner.id,
                    Enrolment.course_id == course_id,
                )
            )
        ).scalar_one_or_none()
        assert enrolment is not None
        assert enrolment.entitlement_id == entitlement.id

        has_access = await licence_service.has_active_licence(
            session, tenant_id=tenant_id, learner_user_id=learner.id, course_id=course_id
        )
        assert has_access is True


async def test_revoke_seat_revokes_entitlement_and_frees_seat(
    tenant_session_factory,
):  # type: ignore[no-untyped-def]
    from src.models.commerce import Entitlement

    tenant_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(tenant_id) as session:
        org = await _make_organisation(session, tenant_id=tenant_id, name="Test Licensee")
        course_id, _ = await _make_course(session, tenant_id=tenant_id, title="Test Course")
        learner = await _make_user(
            session, tenant_id=tenant_id, email=f"learner-{uuid.uuid4().hex[:8]}@example.com"
        )

        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=365)

        licence = await licence_service.create_licence(
            session,
            tenant_id=tenant_id,
            organisation_id=org.id,
            course_id=course_id,
            seats_purchased=1,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        grant = await licence_service.grant_seat(
            session,
            tenant_id=tenant_id,
            licence_id=licence.id,
            learner_user_id=learner.id,
        )
        entitlement_id = grant.entitlement_id
        assert entitlement_id is not None

        await licence_service.revoke_seat(session, tenant_id=tenant_id, grant_id=grant.id)

        entitlement = await session.get(Entitlement, entitlement_id)
        assert entitlement is not None
        assert entitlement.revoked_at is not None

        licence_refetched = await session.get(Licence, licence.id)
        assert licence_refetched is not None
        assert licence_refetched.seats_used == 0

        has_access = await licence_service.has_active_licence(
            session, tenant_id=tenant_id, learner_user_id=learner.id, course_id=course_id
        )
        assert has_access is False


__all__ = []
