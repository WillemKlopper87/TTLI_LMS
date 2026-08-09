"""Seed: permissions, the Phase 1 roles, two demo tenants, break-glass admin.

Data migration, kept separate from the schema revision so a schema rollback does
not silently discard data.

The break-glass administrator is refused when ENVIRONMENT=production — the same
rule check_production_safety() applies at boot, enforced here so a production
database cannot be seeded with one even by accident.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS: list[tuple[str, str]] = [
    ("course:view", "View published courses"),
    ("course:edit", "Create and edit courses"),
    ("course:publish", "Publish or unpublish a course"),
    ("lesson:complete", "Record lesson completion"),
    ("quiz:grade", "Grade open-ended assessment answers"),
    ("certificate:issue", "Issue a certificate"),
    ("certificate:revoke", "Revoke a certificate"),
    ("order:view", "View orders"),
    ("invoice:create", "Issue an invoice"),
    ("payment:approve", "Approve or reject an EFT payment"),
    ("refund:process", "Process a refund"),
    ("user:invite", "Invite a user"),
    ("user:suspend", "Suspend a user"),
    ("analytics:view", "View analytics dashboards"),
    ("audit:read", "Read the audit log"),
    ("tenant:manage", "Change tenant configuration"),
    ("settings:manage", "Change platform settings"),
]

# Six roles for Phase 1. Corporate roles arrive with the corporate phase; the
# permission strings above already anticipate them, so adding a role later is a
# data migration rather than a code change.
ROLES: dict[str, tuple[str, list[str]]] = {
    "guest": ("Guest", ["course:view"]),
    "learner": ("Learner", ["course:view", "lesson:complete"]),
    "content_author": (
        "Content author",
        ["course:view", "course:edit", "course:publish", "quiz:grade"],
    ),
    "finance": (
        "Finance",
        ["order:view", "invoice:create", "payment:approve", "refund:process"],
    ),
    "admin": (
        "Administrator",
        [
            "course:view",
            "course:edit",
            "course:publish",
            "quiz:grade",
            "certificate:issue",
            "certificate:revoke",
            "order:view",
            "user:invite",
            "user:suspend",
            "analytics:view",
            "audit:read",
        ],
    ),
    "super_admin": ("Super administrator", [c for c, _ in PERMISSIONS]),
}

DEMO_TENANTS: list[tuple[str, str, str]] = [
    ("demo", "TTLI Executive Institute", "localhost"),
    ("acme", "Meridian Holdings", "meridian.localhost"),
]


def _uuid7() -> uuid.UUID:
    import time

    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    conn = op.get_bind()

    for code, description in PERMISSIONS:
        conn.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:c, :d)"),
            {"c": code, "d": description},
        )

    for code, (name, perms) in ROLES.items():
        conn.execute(
            sa.text("INSERT INTO roles (code, name) VALUES (:c, :n)"), {"c": code, "n": name}
        )
        for perm in perms:
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_code, permission_code) VALUES (:r, :p)"
                ),
                {"r": code, "p": perm},
            )

    environment = os.getenv("ENVIRONMENT", "local")
    tenant_ids: dict[str, uuid.UUID] = {}

    for slug, name, hostname in DEMO_TENANTS:
        if environment == "production" and slug in {"demo", "acme"}:
            continue
        tenant_id = _uuid7()
        tenant_ids[slug] = tenant_id
        conn.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, :n)"),
            {"i": tenant_id, "s": slug, "n": name},
        )
        conn.execute(
            sa.text(
                "INSERT INTO tenant_domains (id, tenant_id, hostname, is_primary, tls_status) "
                "VALUES (:i, :t, :h, true, 'issued')"
            ),
            {"i": _uuid7(), "t": tenant_id, "h": hostname},
        )

    # --- Break-glass administrator ------------------------------------------
    if os.getenv("BREAK_GLASS_ADMIN_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return
    if environment == "production":
        raise RuntimeError("BREAK_GLASS_ADMIN_ENABLED must not be set when ENVIRONMENT=production")
    if "demo" not in tenant_ids:
        return

    password = os.getenv("BREAK_GLASS_ADMIN_PASSWORD", "")
    if not password:
        raise RuntimeError("BREAK_GLASS_ADMIN_PASSWORD is required when the admin is enabled")

    import base64

    from src.core.crypto import CryptoBox
    from src.core.security import hash_password

    crypto = CryptoBox(
        base64.b64decode(os.environ["FIELD_ENCRYPTION_KEY"]),
        base64.b64decode(os.environ["BLIND_INDEX_KEY"]),
    )
    email = os.getenv("BREAK_GLASS_ADMIN_EMAIL", "admin@ttli.local").strip().lower()
    user_id = _uuid7()

    # users and role_assignments are RLS-forced, so even the table owner has to
    # declare which tenant it is writing for. Without this the INSERT fails the
    # WITH CHECK clause — which is the policy working correctly.
    conn.execute(
        sa.text("SELECT set_config('app.tenant_id', :t, true)"),
        {"t": str(tenant_ids["demo"])},
    )

    conn.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, email_encrypted, email_blind_index, "
            "email_domain, password_hash) VALUES (:i, :t, :e, :b, :d, :p)"
        ),
        {
            "i": user_id,
            "t": tenant_ids["demo"],
            "e": crypto.encrypt(email),
            "b": crypto.blind_index(email),
            "d": email.split("@", 1)[-1],
            "p": hash_password(password),
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_assignments (id, tenant_id, user_id, role_code) "
            "VALUES (:i, :t, :u, 'super_admin')"
        ),
        {"i": _uuid7(), "t": tenant_ids["demo"], "u": user_id},
    )


def downgrade() -> None:
    conn = op.get_bind()

    # audit_events accumulates rows well beyond the seed data — every login
    # writes one — and its FK to tenants is RESTRICT, so those rows must go
    # before DELETE FROM tenants below. The append-only trigger blocks a plain
    # DELETE regardless of role privilege, so it is disabled for this one
    # statement rather than routed around.
    conn.execute(sa.text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only"))
    conn.execute(sa.text("DELETE FROM audit_events"))
    conn.execute(sa.text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))

    # Cleaning up across every tenant. Dropping FORCE lets the table owner
    # bypass the policy for the length of this migration; `row_security = off`
    # would not help, since it makes such queries error rather than bypass.
    rls_tables = ("role_assignments", "users")
    for table in rls_tables:
        conn.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))

    conn.execute(sa.text("DELETE FROM role_assignments"))
    conn.execute(sa.text("DELETE FROM users"))

    for table in rls_tables:
        conn.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    conn.execute(sa.text("DELETE FROM tenant_domains"))
    conn.execute(sa.text("DELETE FROM tenants"))
    conn.execute(sa.text("DELETE FROM role_permissions"))
    conn.execute(sa.text("DELETE FROM roles"))
    conn.execute(sa.text("DELETE FROM permissions"))
