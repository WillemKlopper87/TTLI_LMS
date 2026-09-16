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
    """Get the demo tenant's admin user."""
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
    assert row is not None
    return uuid.UUID(str(row[0]))


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
