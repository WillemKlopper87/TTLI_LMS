"""Multi-tier subscriptions + a second demo course to bundle (02 §6,
REQ-PAY-12).

Resolves 01 §1.4 #5 ("Subscriptions in or out?"), previously blocking on a
customer decision — now decided in, with a concrete shape: renewals are
funded through the *existing* EFT/PO manual-approval checkout flow
(`services/orders.py::_fulfil_order`), not automatic card charging, since
Payfast/Netcash integration still doesn't exist (`routers/orders.py`'s own
docstring, unchanged by this migration). Each billing period is a real
`orders` row tagged with the new `orders.subscription_id`; fulfilling it
grants a fresh, time-bound `entitlements` row via `entitlements.expires_at`
— a column that has existed since `0009` but was never written to until now.

`products.subscription_plan_id` and `subscription_plans.product_id` are a
circular FK pair. No ordering problem in practice: `subscription_plans` is
created first, referencing the already-existing `products` table; the new
`products.subscription_plan_id` column is added afterward, once
`subscription_plans` exists to point at.

No new `CheckConstraint`: `orders.subscription_id`/`orders.organisation_id`
mutual exclusivity (an order is either a seat purchase or a subscription
period, never both) is convention only, the same treatment
`entitlements.user_id`/`entitlements.organisation_id` already gets — not
something to go looking for here (a past incident in this repo, recorded in
docs/HANDOFF.md, involved a check constraint declared only via raw SQL and
invisible to the model; this migration has no such constraint to miss).

`revoke_lapsed_subscriptions` follows `0005`'s SECURITY DEFINER maintenance-
function idiom exactly: the privilege to sweep across every tenant despite
RLS lives in the function's owner, never in the worker process, which
connects as the same least-privileged `app_user` the API does.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("subscription_plans", "subscription_plan_courses", "subscriptions")

SUBSCRIPTION_STATUS_VALUES = ("pending", "active", "cancelled")

SECOND_COURSE_SLUG = "executive-coaching-intensive"


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    subscription_status = pg.ENUM(
        *SUBSCRIPTION_STATUS_VALUES, name="subscription_status", create_type=False
    )
    subscription_status.create(op.get_bind())

    op.create_table(
        "subscription_plans",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "product_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("prices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "billing_interval_days", sa.Integer(), nullable=False, server_default=sa.text("30")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_subscription_plans_tenant_id", "subscription_plans", ["tenant_id"])
    op.create_index(
        "uq_subscription_plans_tenant_slug",
        "subscription_plans",
        ["tenant_id", "slug"],
        unique=True,
    )

    op.create_table(
        "subscription_plan_courses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_subscription_plan_courses_tenant_id", "subscription_plan_courses", ["tenant_id"]
    )
    op.create_index(
        "ix_subscription_plan_courses_plan_id", "subscription_plan_courses", ["plan_id"]
    )
    op.create_index(
        "uq_subscription_plan_courses",
        "subscription_plan_courses",
        ["plan_id", "course_id"],
        unique=True,
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "pending_plan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", subscription_status, nullable=False, server_default="pending"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("last_plan_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index(
        "uq_subscriptions_tenant_user", "subscriptions", ["tenant_id", "user_id"], unique=True
    )

    op.add_column(
        "products",
        sa.Column(
            "subscription_plan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "subscription_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    # products/orders' first writable column since 0020/0016 respectively —
    # same UPDATE-only precedent every prior narrow-column addition set.
    op.execute(f"GRANT UPDATE ON products TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ON orders TO {APP_ROLE}")

    # grace_days here must match services/subscriptions.py::GRACE_DAYS (3) —
    # that constant is what a subscription entitlement's `expires_at` is
    # actually granted with (current_period_end + GRACE_DAYS), so the
    # entitlements sweep below compares against plain now() (no further
    # grace subtraction — it's already baked into expires_at). The
    # subscriptions sweep compares against current_period_end, the pure
    # ungraced billing boundary, so it re-derives the same real-world cutoff
    # independently via its own grace_days subtraction.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION revoke_lapsed_subscriptions(grace_days int DEFAULT 3)
        RETURNS int
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            subscription_cutoff timestamptz := now() - make_interval(days => grace_days);
            n int;
        BEGIN
            UPDATE subscriptions
            SET status = 'cancelled'
            WHERE status = 'active' AND current_period_end < subscription_cutoff;

            UPDATE entitlements
            SET revoked_at = now()
            WHERE expires_at IS NOT NULL AND expires_at < now() AND revoked_at IS NULL;
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END;
        $$;
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION revoke_lapsed_subscriptions(int) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION revoke_lapsed_subscriptions(int) TO {APP_ROLE}")

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES "
            "('subscription_plan:manage', 'Create and manage subscription plans and their course bundles')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('content_author', 'subscription_plan:manage'), "
            "('admin', 'subscription_plan:manage'), "
            "('super_admin', 'subscription_plan:manage')"
        )
    )

    # --- Seed: a second demo course (so the two demo plans below can
    # actually differ), and two demo subscription plans per tenant.
    # Structural content only, same "not real TTLI curriculum" precedent
    # 0009/0011 already set.
    second_course_id = _uuid7()
    conn.execute(
        sa.text(
            "INSERT INTO courses (id, slug, title, description, state) "
            "VALUES (:id, :slug, "
            "'Executive Coaching Intensive', "
            "'A second demo course seeded so subscription plans have more "
            "than one course to meaningfully bundle.', "
            "'published')"
        ),
        {"id": second_course_id, "slug": SECOND_COURSE_SLUG},
    )
    second_module_id = _uuid7()
    conn.execute(
        sa.text(
            "INSERT INTO modules (id, course_id, title, position) "
            "VALUES (:id, :c, 'Coaching Fundamentals', 1)"
        ),
        {"id": second_module_id, "c": second_course_id},
    )
    conn.execute(
        sa.text(
            "INSERT INTO lessons "
            "(id, module_id, title, position, activity_type, access_level, body, completion_rules) "
            "VALUES (:id, :m, 'Introduction to Coaching', 1, 'document', 'paid', "
            "'Placeholder document content for the introductory lesson.', "
            "CAST(:rules AS JSONB))"
        ),
        {"id": _uuid7(), "m": second_module_id, "rules": '{"minimum_time_seconds": 30}'},
    )

    for slug in ("demo", "acme"):
        tenant_id = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}
        ).scalar()
        if tenant_id is None:
            continue
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})

        conn.execute(
            sa.text(
                "INSERT INTO course_tenant_assignments (id, tenant_id, course_id, is_bespoke) "
                "VALUES (:id, :t, :c, false)"
            ),
            {"id": _uuid7(), "t": tenant_id, "c": second_course_id},
        )

        first_course_id = conn.execute(
            sa.text("SELECT id FROM courses WHERE slug = 'executive-leadership-certificate'")
        ).scalar()
        if first_course_id is None:
            continue

        for plan_slug, plan_name, description, amount, course_ids in (
            (
                "leadership-track",
                "Leadership Track",
                "Renewing access to the Executive Leadership Certificate.",
                "750.00",
                (first_course_id,),
            ),
            (
                "full-library",
                "Full Library",
                "Renewing access to every course in the catalogue.",
                "1200.00",
                (first_course_id, second_course_id),
            ),
        ):
            product_id = _uuid7()
            conn.execute(
                sa.text(
                    "INSERT INTO products (id, tenant_id, slug, name, description, kind, is_active) "
                    "VALUES (:id, :t, :slug, :n, :d, 'subscription', true)"
                ),
                {
                    "id": product_id,
                    "t": tenant_id,
                    "slug": f"subscription-{plan_slug}",
                    "n": plan_name,
                    "d": description,
                },
            )
            price_id = _uuid7()
            conn.execute(
                sa.text(
                    "INSERT INTO prices (id, tenant_id, product_id, currency, unit_amount, tax_behaviour) "
                    "VALUES (:id, :t, :p, 'ZAR', :amount, 'exclusive')"
                ),
                {"id": price_id, "t": tenant_id, "p": product_id, "amount": amount},
            )
            plan_id = _uuid7()
            conn.execute(
                sa.text(
                    "INSERT INTO subscription_plans "
                    "(id, tenant_id, slug, name, description, product_id, price_id, billing_interval_days) "
                    "VALUES (:id, :t, :slug, :n, :d, :p, :pr, 30)"
                ),
                {
                    "id": plan_id,
                    "t": tenant_id,
                    "slug": plan_slug,
                    "n": plan_name,
                    "d": description,
                    "p": product_id,
                    "pr": price_id,
                },
            )
            conn.execute(
                sa.text("UPDATE products SET subscription_plan_id = :plan WHERE id = :p"),
                {"plan": plan_id, "p": product_id},
            )
            for course_id in course_ids:
                conn.execute(
                    sa.text(
                        "INSERT INTO subscription_plan_courses (id, tenant_id, plan_id, course_id) "
                        "VALUES (:id, :t, :plan, :c)"
                    ),
                    {"id": _uuid7(), "t": tenant_id, "plan": plan_id, "c": course_id},
                )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = 'subscription_plan:manage'")
    )
    conn.execute(sa.text("DELETE FROM permissions WHERE code = 'subscription_plan:manage'"))

    op.execute("DROP FUNCTION IF EXISTS revoke_lapsed_subscriptions(int)")

    op.execute(f"REVOKE UPDATE ON orders FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON products FROM {APP_ROLE}")

    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_column("orders", "subscription_id")
    op.drop_column("products", "subscription_plan_id")

    op.drop_table("subscriptions")
    op.drop_table("subscription_plan_courses")
    op.drop_table("subscription_plans")
    op.execute("DROP TYPE IF EXISTS subscription_status")

    # The seeded subscription products/prices — deleted only now that
    # subscription_plans (which held a RESTRICT-ing product_id FK to
    # these exact rows) is gone. Scoped tightly (kind + slug prefix) to
    # match only what this migration's own seed inserted, matching
    # 0016/0011's precedent of deleting exactly what was seeded, not a
    # broader pattern that could catch real tenant-created data.
    conn.execute(
        sa.text(
            "DELETE FROM prices WHERE product_id IN "
            "(SELECT id FROM products WHERE kind = 'subscription' AND slug LIKE 'subscription-%')"
        )
    )
    conn.execute(
        sa.text("DELETE FROM products WHERE kind = 'subscription' AND slug LIKE 'subscription-%'")
    )

    # course_tenant_assignments/lessons/modules cascade or are removed with
    # their parent; the course row itself needs an explicit delete.
    conn.execute(
        sa.text(
            "DELETE FROM course_tenant_assignments WHERE course_id IN "
            "(SELECT id FROM courses WHERE slug = :slug)"
        ),
        {"slug": SECOND_COURSE_SLUG},
    )
    conn.execute(
        sa.text(
            "DELETE FROM lessons WHERE module_id IN "
            "(SELECT m.id FROM modules m JOIN courses c ON c.id = m.course_id WHERE c.slug = :slug)"
        ),
        {"slug": SECOND_COURSE_SLUG},
    )
    conn.execute(
        sa.text(
            "DELETE FROM modules WHERE course_id IN (SELECT id FROM courses WHERE slug = :slug)"
        ),
        {"slug": SECOND_COURSE_SLUG},
    )
    conn.execute(sa.text("DELETE FROM courses WHERE slug = :slug"), {"slug": SECOND_COURSE_SLUG})
