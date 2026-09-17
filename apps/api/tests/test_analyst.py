"""Analyst workspace: engagement policy and report state machine (BACKLOG L5).

Test coverage for:
- Engagement assignment and revocation
- Access policy: engagement validity, expiration, revocation
- Report state machine: allowed/disallowed transitions
- Immutability after acceptance
- Version bumping on resubmission
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.integration


@pytest.fixture
async def tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    """Get the demo tenant ID."""
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


@pytest.fixture
async def admin_user_id(  # type: ignore[no-untyped-def]
    tenant_session_factory,
    tenant_id: uuid.UUID,
) -> uuid.UUID:
    """Get the demo tenant's admin user, creating one if none is seeded.

    A fresh database (migrations only, no seed script) has no users at
    all for the demo tenant — mirrors analyst_user_id's create-if-missing
    pattern rather than assuming external seed data exists.
    """
    from src.core.config import get_settings
    from src.core.crypto import CryptoBox
    from src.models.rbac import RoleAssignment
    from src.models.user import User

    settings = get_settings()
    crypto = CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())

    async with tenant_session_factory(tenant_id) as s:
        row = (
            await s.execute(
                sa.text(
                    """
                    SELECT u.id FROM users u
                    JOIN role_assignments ra ON u.id = ra.user_id
                    WHERE ra.tenant_id = :tid AND ra.role_code = 'admin'
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).first()
        if row is not None:
            return uuid.UUID(str(row[0]))

        admin_id = uuid.uuid4()
        user = User(
            id=admin_id,
            tenant_id=tenant_id,
            email_encrypted=crypto.encrypt("analyst-admin@example.com"),
            email_blind_index=crypto.blind_index("analyst-admin@example.com"),
            email_domain="example.com",
            full_name_encrypted=crypto.encrypt("Admin Name"),
            status="active",
            is_guest=False,
        )
        s.add(user)
        await s.flush()
        s.add(RoleAssignment(tenant_id=tenant_id, user_id=admin_id, role_code="admin"))
        await s.flush()
    return admin_id


@pytest.fixture
async def analyst_user_id(  # type: ignore[no-untyped-def]
    tenant_session_factory,
    tenant_id: uuid.UUID,
) -> uuid.UUID:
    """Create an analyst user for testing."""
    from src.core.config import get_settings
    from src.core.crypto import CryptoBox

    settings = get_settings()
    crypto = CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())

    async with tenant_session_factory(tenant_id) as s:
        # Check if analyst exists, create if not
        existing = (
            await s.execute(
                sa.text("SELECT id FROM users WHERE email_blind_index = :idx LIMIT 1"),
                {"idx": crypto.blind_index("analyst@example.com")},
            )
        ).scalar_one_or_none()

        if existing:
            return uuid.UUID(str(existing))

        # Create a new analyst user
        analyst_id = uuid.uuid4()
        from src.models.user import User

        user = User(
            id=analyst_id,
            tenant_id=tenant_id,
            email_encrypted=crypto.encrypt("analyst@example.com"),
            email_blind_index=crypto.blind_index("analyst@example.com"),
            email_domain="example.com",
            full_name_encrypted=crypto.encrypt("Analyst Name"),
            status="active",
            is_guest=False,
        )
        s.add(user)
        await s.flush()
    return analyst_id


class TestEngagementAssignment:
    """Test engagement assignment and revocation."""

    async def test_assign_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Assign an analyst to an instance."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="External psychology assessment",
            )
            assert engagement.analyst_user_id == analyst_user_id
            assert engagement.instance_id == instance_id
            assert engagement.revoked_at is None

    async def test_revoke_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Revoke an engagement."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="External psychology assessment",
            )
            engagement_id = engagement.id

        async with tenant_session_factory(tenant_id) as s:
            revoked = await analyst.revoke_engagement(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement_id,
            )
            assert revoked.revoked_at is not None


class TestEngagementPolicy:
    """Test engagement access policy."""

    async def test_check_valid_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Valid engagement passes the policy check."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            engagement_id = engagement.id

        async with tenant_session_factory(tenant_id) as s:
            checked = await analyst.check_engagement_access(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
            )
            assert checked.id == engagement_id

    async def test_check_revoked_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Revoked engagement fails the policy check."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            engagement_id = engagement.id

        async with tenant_session_factory(tenant_id) as s:
            await analyst.revoke_engagement(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement_id,
            )

        async with tenant_session_factory(tenant_id) as s:
            with pytest.raises(analyst.EngagementRevoked):
                await analyst.check_engagement_access(
                    s,
                    tenant_id=tenant_id,
                    analyst_user_id=analyst_user_id,
                    instance_id=instance_id,
                )

    async def test_check_expired_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Expired engagement fails the policy check."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        # Engagement in the past
        ends_at = datetime.now(UTC) - timedelta(hours=1)
        starts_at = ends_at - timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

        async with tenant_session_factory(tenant_id) as s:
            with pytest.raises(analyst.EngagementExpired):
                await analyst.check_engagement_access(
                    s,
                    tenant_id=tenant_id,
                    analyst_user_id=analyst_user_id,
                    instance_id=instance_id,
                )

    async def test_check_missing_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Missing engagement fails the policy check."""
        from src.services import analyst

        instance_id = uuid.uuid4()

        async with tenant_session_factory(tenant_id) as s:
            with pytest.raises(analyst.EngagementNotFound):
                await analyst.check_engagement_access(
                    s,
                    tenant_id=tenant_id,
                    analyst_user_id=analyst_user_id,
                    instance_id=instance_id,
                )


class TestReportStateMachine:
    """Test report state machine transitions."""

    async def test_create_draft_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Create a draft report."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            assert report.status.value == "draft"
            assert report.version == 1
            assert report.submitted_at is None

    async def test_cannot_create_two_drafts_for_engagement(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Cannot create two drafts for the same engagement."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            # Second draft should fail
            with pytest.raises(analyst.ReportAlreadyExists):
                await analyst.create_report_draft(
                    s,
                    tenant_id=tenant_id,
                    engagement_id=engagement.id,
                    author_user_id=analyst_user_id,
                    title="Another Report",
                )

    async def test_submit_draft_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Submit a draft report (requires summary or attachment)."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            # Add summary and submit
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            assert submitted.status.value == "submitted"
            assert submitted.submitted_at is not None

    async def test_submit_without_summary_or_attachment_fails(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Cannot submit without summary or attachment."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            with pytest.raises(analyst.InvalidReportTransition):
                await analyst.submit_report(
                    s,
                    tenant_id=tenant_id,
                    report_id=report.id,
                    author_user_id=analyst_user_id,
                )

    async def test_return_submitted_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Reviewer returns a submitted report."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            returned = await analyst.return_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
                decision_note="Please expand the clinical reasoning section.",
            )

            assert returned.status.value == "returned"
            assert returned.decision_note == "Please expand the clinical reasoning section."

    async def test_resubmit_returned_report_bumps_version(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Resubmitting a returned report bumps the version."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            returned = await analyst.return_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
                decision_note="Please expand.",
            )

            resubmitted = await analyst.resubmit_returned_report(
                s,
                tenant_id=tenant_id,
                report_id=returned.id,
                author_user_id=analyst_user_id,
            )

            assert resubmitted.status.value == "submitted"
            assert resubmitted.version == 2

    async def test_accept_submitted_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Reviewer accepts a submitted report (makes it immutable)."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            accepted = await analyst.accept_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
            )

            assert accepted.status.value == "accepted"
            assert accepted.decided_by == admin_user_id

    async def test_withdraw_draft_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Analyst can withdraw a draft report."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            withdrawn = await analyst.withdraw_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            assert withdrawn.status.value == "withdrawn"

    async def test_cannot_withdraw_accepted_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Cannot withdraw an accepted report."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            accepted = await analyst.accept_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
            )

            with pytest.raises(analyst.InvalidReportTransition):
                await analyst.withdraw_report(
                    s,
                    tenant_id=tenant_id,
                    report_id=accepted.id,
                    author_user_id=analyst_user_id,
                )

    async def test_release_accepted_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """Reviewer can release an accepted report to the organisation."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )

            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Client shows signs of attention deficit."
            await s.flush()

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )

            accepted = await analyst.accept_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
            )

            released = await analyst.release_report(
                s,
                tenant_id=tenant_id,
                report_id=accepted.id,
                reviewer_user_id=admin_user_id,
            )

            assert released.released_at is not None


class TestReportSummaryAndAttachments:
    """Test the real-API path for satisfying submit's summary/attachment gate."""

    async def test_update_report_summary_then_submit(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """update_report_summary lets the analyst set a summary through
        the service layer (not by writing to the ORM object directly, as
        every other test in this file does) and then submit succeeds."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            updated = await analyst.update_report_summary(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
                summary="Client shows signs of attention deficit.",
            )
            assert updated.summary == "Client shows signs of attention deficit."

            submitted = await analyst.submit_report(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
            )
            assert submitted.status.value == "submitted"

    async def test_update_report_summary_rejects_non_author(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            with pytest.raises(analyst.ReportNotFound):
                await analyst.update_report_summary(
                    s,
                    tenant_id=tenant_id,
                    report_id=report.id,
                    author_user_id=admin_user_id,
                    summary="Not my report.",
                )

    async def test_update_report_summary_rejects_accepted_report(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Initial summary."
            await s.flush()
            submitted = await analyst.submit_report(
                s, tenant_id=tenant_id, report_id=report.id, author_user_id=analyst_user_id
            )
            await analyst.accept_report(
                s, tenant_id=tenant_id, report_id=submitted.id, reviewer_user_id=admin_user_id
            )

            with pytest.raises(analyst.ReportImmutable):
                await analyst.update_report_summary(
                    s,
                    tenant_id=tenant_id,
                    report_id=report.id,
                    author_user_id=analyst_user_id,
                    summary="Trying to edit after acceptance.",
                )

    async def test_add_report_attachment_then_submit_without_summary(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        """A clean attachment alone (no summary) satisfies the submit gate."""
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )

            attachment = await analyst.add_report_attachment(
                s,
                tenant_id=tenant_id,
                report_id=report.id,
                author_user_id=analyst_user_id,
                object_key="reports/test/report.pdf",
                filename="report.pdf",
                content_type="application/pdf",
                size_bytes=1024,
            )
            assert attachment.scan_result == "clean"

            attachments = await analyst.list_report_attachments(
                s, tenant_id=tenant_id, report_id=report.id
            )
            assert len(attachments) == 1

            submitted = await analyst.submit_report(
                s, tenant_id=tenant_id, report_id=report.id, author_user_id=analyst_user_id
            )
            assert submitted.status.value == "submitted"


class TestReportAuditTrail:
    """Every report transition leaves an audit event, not just analyst reads."""

    async def test_full_lifecycle_leaves_audit_events_for_every_transition(
        self,
        tenant_session_factory,  # type: ignore[no-untyped-def]
        tenant_id: uuid.UUID,
        admin_user_id: uuid.UUID,
        analyst_user_id: uuid.UUID,
    ) -> None:
        from src.models.audit import AuditAction, AuditEvent
        from src.services import analyst

        instance_id = uuid.uuid4()
        starts_at = datetime.now(UTC)
        ends_at = starts_at + timedelta(days=7)

        async with tenant_session_factory(tenant_id) as s:
            engagement = await analyst.assign_engagement(
                s,
                tenant_id=tenant_id,
                analyst_user_id=analyst_user_id,
                instance_id=instance_id,
                assigned_by=admin_user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                purpose="Assessment review",
            )
            report = await analyst.create_report_draft(
                s,
                tenant_id=tenant_id,
                engagement_id=engagement.id,
                author_user_id=analyst_user_id,
                title="Psychology Assessment Report",
            )
            report.summary = "Initial summary."
            await s.flush()

            submitted = await analyst.submit_report(
                s, tenant_id=tenant_id, report_id=report.id, author_user_id=analyst_user_id
            )
            returned = await analyst.return_report(
                s,
                tenant_id=tenant_id,
                report_id=submitted.id,
                reviewer_user_id=admin_user_id,
                decision_note="Please add more detail.",
            )
            resubmitted = await analyst.resubmit_returned_report(
                s, tenant_id=tenant_id, report_id=returned.id, author_user_id=analyst_user_id
            )
            accepted = await analyst.accept_report(
                s, tenant_id=tenant_id, report_id=resubmitted.id, reviewer_user_id=admin_user_id
            )
            await analyst.release_report(
                s, tenant_id=tenant_id, report_id=accepted.id, reviewer_user_id=admin_user_id
            )

            events = (
                await s.execute(
                    sa.select(AuditEvent.action).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.entity_type == "report",
                        AuditEvent.entity_id == report.id,
                    )
                )
            ).scalars().all()

            assert set(events) == {
                AuditAction.REPORT_SUBMITTED,
                AuditAction.REPORT_RETURNED,
                AuditAction.REPORT_RESUBMITTED,
                AuditAction.REPORT_ACCEPTED,
                AuditAction.REPORT_RELEASED,
            }


class TestAnalystReviewerRoles:
    """0049's dedicated analyst/reviewer roles grant exactly the split
    permissions the spec describes, without needing full admin."""

    async def test_analyst_role_grants_exactly_analyse_and_submit(
        self, tenant_session_factory  # type: ignore[no-untyped-def]
    ) -> None:
        async with tenant_session_factory(None) as s:
            perms = (
                await s.execute(
                    sa.text(
                        "SELECT permission_code FROM role_permissions WHERE role_code = 'analyst'"
                    )
                )
            ).scalars().all()
        assert set(perms) == {"assessment:analyse", "report:submit"}

    async def test_reviewer_role_grants_exactly_report_review(
        self, tenant_session_factory  # type: ignore[no-untyped-def]
    ) -> None:
        async with tenant_session_factory(None) as s:
            perms = (
                await s.execute(
                    sa.text(
                        "SELECT permission_code FROM role_permissions WHERE role_code = 'reviewer'"
                    )
                )
            ).scalars().all()
        assert set(perms) == {"report:review"}
