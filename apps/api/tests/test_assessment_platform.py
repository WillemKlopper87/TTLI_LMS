"""Assessment platform foundation: templates, instances, RLS isolation.

Tests the first slice of the assessment platform:
- Migration applies cleanly
- RLS actually isolates tenants (cross-tenant read returns nothing)
- Template creation and listing
- Instance creation and listing
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from src.models.assessment_template import (
    AssessmentInstance,
    AssessmentTemplate,
)
from src.services import assessment_template

pytestmark = pytest.mark.integration


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore
    """Get demo tenant ID."""
    async with tenant_session_factory(None) as s:
        row = (await s.execute(text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _other_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore
    """Create a second tenant and return its ID."""
    async with tenant_session_factory(None) as s:
        stmt = text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name) RETURNING id")
        result = await s.execute(
            stmt,
            {
                "id": str(uuid.uuid4()),
                "slug": f"other-{uuid.uuid4().hex[:8]}",
                "name": "Other Tenant",
            },
        )
        row = result.first()
        await s.commit()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _create_organisation(tenant_session_factory, tenant_id: uuid.UUID) -> uuid.UUID:  # type: ignore
    """Create an organisation in the tenant."""
    async with tenant_session_factory(tenant_id) as s:
        stmt = text(
            "INSERT INTO organisations (id, tenant_id, name) "
            "VALUES (:id, :tenant_id, :name) RETURNING id"
        )
        result = await s.execute(
            stmt,
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "name": "Test Organisation",
            },
        )
        row = result.first()
        await s.commit()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def test_migration_creates_assessment_tables(
    tenant_session_factory,  # type: ignore
) -> None:
    """Verify migration 0047 creates the assessment tables with RLS."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    async with tenant_session_factory(demo_id) as s:
        # Verify tables exist
        tables = [
            "assessment_templates",
            "assessment_template_questions",
            "assessment_instances",
            "assessment_subjects",
            "assessment_invitations",
            "assessment_responses",
            "assessment_subject_results",
        ]
        for table in tables:
            result = await s.execute(
                text(f"SELECT 1 FROM {table} LIMIT 1")  # noqa: S608
            )
            # Just checking it doesn't raise; table exists
            result.first()


async def test_rls_isolates_templates_across_tenants(
    tenant_session_factory,  # type: ignore
) -> None:
    """Cross-tenant read of templates returns nothing (RLS isolation)."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    other_id = await _other_tenant_id(tenant_session_factory)

    # Create a template in demo tenant
    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="test-template",
            title="Test Template",
            kind="org_survey",
        )
        await s.commit()
        template_id = template.id

    # Try to read it from other tenant — should get nothing
    async with tenant_session_factory(other_id) as s:
        stmt = select(AssessmentTemplate).where(AssessmentTemplate.id == template_id)
        result = await s.scalar(stmt)
        assert result is None, "RLS should prevent cross-tenant template read"


async def test_rls_isolates_instances_across_tenants(
    tenant_session_factory,  # type: ignore
) -> None:
    """Cross-tenant read of instances returns nothing (RLS isolation)."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    other_id = await _other_tenant_id(tenant_session_factory)
    demo_org_id = await _create_organisation(tenant_session_factory, demo_id)

    # Create template and instance in demo tenant
    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="test-template-2",
            title="Test Template 2",
            kind="org_survey",
        )
        instance = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=demo_org_id,
            title="Test Instance",
        )
        await s.commit()
        instance_id = instance.id

    # Try to read it from other tenant — should get nothing
    async with tenant_session_factory(other_id) as s:
        stmt = select(AssessmentInstance).where(AssessmentInstance.id == instance_id)
        result = await s.scalar(stmt)
        assert result is None, "RLS should prevent cross-tenant instance read"


async def test_create_template(tenant_session_factory) -> None:  # type: ignore
    """Create a template and verify fields."""
    demo_id = await _demo_tenant_id(tenant_session_factory)

    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="engagement-analysis",
            title="TTLI Engagement Analysis",
            kind="org_survey",
            description="A 50-question engagement diagnostic",
            response_mode="anonymous",
            minimum_group_size=3,
        )

        assert template.id is not None
        assert template.tenant_id == demo_id
        assert template.slug == "engagement-analysis"
        assert template.title == "TTLI Engagement Analysis"
        assert template.kind == "org_survey"
        assert template.response_mode == "anonymous"
        assert template.minimum_group_size == 3
        assert template.status == "draft"
        assert template.version == 1


async def test_list_templates(tenant_session_factory) -> None:  # type: ignore
    """List templates for a tenant."""
    demo_id = await _demo_tenant_id(tenant_session_factory)

    async with tenant_session_factory(demo_id) as s:
        # Create two templates
        t1 = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="template-1",
            title="Template 1",
            kind="org_survey",
        )
        t2 = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="template-2",
            title="Template 2",
            kind="multi_rater",
        )

    async with tenant_session_factory(demo_id) as s:
        # List templates
        rows = await assessment_template.list_templates(s, tenant_id=demo_id)

        assert len(rows) >= 2
        ids = [t.id for t, _ in rows]
        assert t1.id in ids
        assert t2.id in ids


async def test_create_instance(tenant_session_factory) -> None:  # type: ignore
    """Create an instance for an organisation."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    org_id = await _create_organisation(tenant_session_factory, demo_id)

    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="test-template-3",
            title="Test Template 3",
            kind="org_survey",
        )
        await s.flush()

        instance = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=org_id,
            title="H1 2026 Engagement Survey",
        )

        assert instance.id is not None
        assert instance.tenant_id == demo_id
        assert instance.template_id == template.id
        assert instance.template_version == template.version
        assert instance.organisation_id == org_id
        assert instance.title == "H1 2026 Engagement Survey"
        assert instance.status == "draft"
        assert instance.evaluation_role == "standalone"
        assert instance.pair_id is None


async def test_create_instance_with_pre_post_pairing(
    tenant_session_factory,  # type: ignore
) -> None:
    """Create pre/post paired instances."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    org_id = await _create_organisation(tenant_session_factory, demo_id)

    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="360-lwia",
            title="360 Lead With Intent Assessment",
            kind="multi_rater",
        )
        await s.flush()

        pair_id = uuid.uuid4()
        pre = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=org_id,
            title="Q1 2026 360 (Pre)",
            evaluation_role="pre",
            pair_id=pair_id,
        )
        post = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=org_id,
            title="Q3 2026 360 (Post)",
            evaluation_role="post",
            pair_id=pair_id,
        )

        assert pre.evaluation_role == "pre"
        assert post.evaluation_role == "post"
        assert pre.pair_id == pair_id
        assert post.pair_id == pair_id


async def test_create_instance_validates_pairing_constraint(
    tenant_session_factory,  # type: ignore
) -> None:
    """Validate that standalone/pre/post pairing constraint is enforced."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    org_id = await _create_organisation(tenant_session_factory, demo_id)

    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="test-template-4",
            title="Test Template 4",
            kind="org_survey",
        )
        await s.flush()

        # Standalone with pair_id should raise
        from src.core.errors import AppError

        with pytest.raises(AppError):
            await assessment_template.create_instance(
                s,
                tenant_id=demo_id,
                template_id=template.id,
                organisation_id=org_id,
                title="Should Fail",
                evaluation_role="standalone",
                pair_id=uuid.uuid4(),
            )


async def test_list_instances(tenant_session_factory) -> None:  # type: ignore
    """List instances for a tenant and organisation."""
    demo_id = await _demo_tenant_id(tenant_session_factory)
    org_id = await _create_organisation(tenant_session_factory, demo_id)

    async with tenant_session_factory(demo_id) as s:
        template = await assessment_template.create_template(
            s,
            tenant_id=demo_id,
            slug="test-template-5",
            title="Test Template 5",
            kind="org_survey",
        )
        await s.flush()

        i1 = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=org_id,
            title="Instance 1",
        )
        i2 = await assessment_template.create_instance(
            s,
            tenant_id=demo_id,
            template_id=template.id,
            organisation_id=org_id,
            title="Instance 2",
        )

    async with tenant_session_factory(demo_id) as s:
        instances = await assessment_template.list_instances(
            s, tenant_id=demo_id, organisation_id=org_id
        )

        assert len(instances) >= 2
        ids = [inst.id for inst in instances]
        assert i1.id in ids
        assert i2.id in ids
