"""Tests for programmes (entry paths) feature (0049).

Covers: migration correctness, RLS isolation, cohort creation with participants.
"""

from __future__ import annotations

import uuid

import pytest
from src.models.programme import Cohort, CohortMember, CohortStep
from src.services import programmes

pytestmark = pytest.mark.integration


async def test_migration_converts_learning_path_courses_to_kind_course_steps(
    tenant_session_factory,
):
    """Verify migration: every learning_path_courses row becomes a kind='course' step."""
    import sqlalchemy as sa

    # Get demo tenant
    async with tenant_session_factory(None) as s:
        demo_tenant_id_row = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).first()
    assert demo_tenant_id_row
    demo_tenant_id = uuid.UUID(str(demo_tenant_id_row[0]))

    # In the demo tenant, find existing learning paths and their course mappings
    async with tenant_session_factory(demo_tenant_id) as session:
        # Check that learning_path_steps exists and learning_path_courses does not
        tables_exist = await session.execute(
            sa.text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_name IN ('learning_path_steps', 'learning_path_courses')
                AND table_schema = 'public'
                """
            )
        )
        table_names = [row[0] for row in tables_exist.fetchall()]

        # After migration, we should have learning_path_steps and NOT learning_path_courses
        assert "learning_path_steps" in table_names
        assert "learning_path_courses" not in table_names

        # If there are any steps, verify they are course steps with the right structure
        steps = await session.execute(
            sa.text("SELECT kind, course_id FROM learning_path_steps LIMIT 1")
        )
        step_row = steps.first()
        if step_row:
            kind, course_id = step_row
            assert kind == "course", "Migration should convert all rows as kind='course'"
            assert course_id is not None, "Course steps must have course_id"


async def test_rls_isolates_cohorts_across_tenants(tenant_session_factory):
    """Verify RLS: cohorts from one tenant are invisible to another."""
    import sqlalchemy as sa

    # Get two different tenant IDs
    async with tenant_session_factory(None) as s:
        tenants = (await s.execute(sa.text("SELECT id FROM tenants LIMIT 2"))).fetchall()
    assert len(tenants) >= 2
    tenant1_id = uuid.UUID(str(tenants[0][0]))
    tenant2_id = uuid.UUID(str(tenants[1][0]))

    # Create a cohort in tenant1
    async with tenant_session_factory(tenant1_id) as session:
        cohort1 = Cohort(
            tenant_id=tenant1_id,
            title="Tenant1 Programme",
            status="planned",
        )
        session.add(cohort1)
        await session.commit()
        cohort1_id = cohort1.id

    # Verify tenant2 cannot see tenant1's cohort via RLS
    async with tenant_session_factory(tenant2_id) as session:
        # Query for the cohort created in tenant1
        result = await session.execute(sa.select(Cohort).where(Cohort.id == cohort1_id))
        found_cohort = result.scalar()
        assert found_cohort is None, "Tenant2 should not see Tenant1's cohort due to RLS"


async def test_cohort_creation_with_participants(tenant_session_factory):
    """Verify cohort creation works with participants, pre-creates cohort steps."""
    import sqlalchemy as sa

    async with tenant_session_factory(None) as s:
        demo_tenant_id_row = (
            await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))
        ).first()
    assert demo_tenant_id_row
    demo_tenant_id = uuid.UUID(str(demo_tenant_id_row[0]))

    async with tenant_session_factory(demo_tenant_id) as session:
        # Always create a fresh path rather than reusing any existing one:
        # when the suite runs together (as CI does), an existing
        # tenant-assigned path may belong to another test module and
        # already hold steps at position 0/1, colliding with the ones
        # this test creates below.
        path_id = uuid.uuid4()
        await session.execute(
            sa.text(
                """
                INSERT INTO learning_paths (id, slug, title, state)
                VALUES (:id, :slug, :title, :state)
                """
            ),
            {
                "id": path_id,
                "slug": f"test-path-{path_id.hex[:8]}",
                "title": "Test Path",
                "state": "published",
            },
        )
        # create_cohort scopes LearningPath lookups through this
        # assignment table (a global path is invisible to a tenant
        # without one) — without it, create_cohort correctly 404s.
        await session.execute(
            sa.text(
                """
                INSERT INTO learning_path_tenant_assignments (id, tenant_id, learning_path_id)
                VALUES (:id, :tenant_id, :path_id)
                """
            ),
            {"id": uuid.uuid4(), "tenant_id": demo_tenant_id, "path_id": path_id},
        )

        # Create some steps for the path
        step_ids = []
        for i in range(2):
            step_id = uuid.uuid4()
            await session.execute(
                sa.text(
                    """
                    INSERT INTO learning_path_steps
                    (id, learning_path_id, position, kind, title)
                    VALUES (:id, :path_id, :position, 'course', :title)
                    """
                ),
                {
                    "id": step_id,
                    "path_id": path_id,
                    "position": i,
                    "title": f"Step {i}",
                },
            )
            step_ids.append(step_id)

        await session.commit()

    # A committed session's transaction is closed; every subsequent
    # operation needs a session of its own, matching the pattern
    # test_privacy.py/test_assessment_platform.py already use.
    async with tenant_session_factory(demo_tenant_id) as session:
        # Get some test users
        users = (
            await session.execute(
                sa.text("SELECT id FROM users WHERE tenant_id = :tid LIMIT 2"),
                {"tid": demo_tenant_id},
            )
        ).fetchall()

        participant_ids = [uuid.UUID(str(u[0])) for u in users]

        # Now create a cohort with participants
        cohort = await programmes.create_cohort(
            session,
            tenant_id=demo_tenant_id,
            learning_path_id=path_id,
            title="Test Cohort",
            participants=[
                {"user_id": participant_ids[0], "role": "participant"},
                {"user_id": participant_ids[1], "role": "observer"},
            ]
            if len(participant_ids) >= 2
            else [{"user_id": participant_ids[0], "role": "participant"}],
        )
        await session.commit()
        cohort_id = cohort.id
        assert cohort.tenant_id == demo_tenant_id
        assert cohort.learning_path_id == path_id
        assert cohort.status == "planned"

    async with tenant_session_factory(demo_tenant_id) as session:
        # Verify cohort_steps were pre-created for each path step
        cohort_steps = (
            await session.execute(sa.select(CohortStep).where(CohortStep.cohort_id == cohort_id))
        ).scalars()
        steps_list = list(cohort_steps)
        assert len(steps_list) == len(step_ids), (
            "Should have created cohort_steps for each path step"
        )

        # Verify cohort_members were created
        members = (
            await session.execute(
                sa.select(CohortMember).where(CohortMember.cohort_id == cohort_id)
            )
        ).scalars()
        members_list = list(members)
        assert len(members_list) > 0, "Should have created cohort_members"
        assert len(members_list) == len(participant_ids), "Should have one member per participant"

        # Verify roles were set correctly
        roles = {m.user_id: m.role for m in members_list}
        assert roles[participant_ids[0]] == "participant"
        if len(participant_ids) >= 2:
            assert roles[participant_ids[1]] == "observer"
