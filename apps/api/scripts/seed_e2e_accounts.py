"""Create (or repair) the accounts the Playwright specs sign in as.

Until now these accounts existed only in whatever dev database the agent
that wrote the spec happened to be using -- `ops-admin@example.com` and
`smoke-agent@example.com` are referenced by name in `apps/web/e2e/` and by
`docs/NEXT_AGENT_BRIEF.md`, but nothing in the repo could create them. On
2026-08-27 that bill came due: `smoke-agent@example.com` was simply absent
from the dev database, so `learner.spec.ts` could only ever have failed at
the login form -- which reads as "the dashboard is broken" rather than
"the fixture is missing".

**One account per spec, deliberately.** Login is rate-limited to 5/min per
account (`routers/auth.py`, 03 section 1.8) and a fixed-window counter admits
exactly the fifth hit. `admin.spec.ts` spends four of those on
`ops-admin@`; a fifth spec sharing that account would sit exactly on the
ceiling, and CI's one retry would push it over into a 429 that surfaces as
"those credentials are not valid" -- the same misleading failure again.
So `session-refresh.spec.ts` gets `refresh-admin@`, and the next spec gets
its own, not a fifth login on someone else's.

Roles are least-privilege per spec, not super_admin everywhere:
`refresh-admin@` needs `product:manage` for /admin/catalogue and nothing
else, which is the `admin` role.

Idempotent: matched on the email blind index, so re-running resets the
password and enforces exactly the declared role rather than creating
duplicates or retaining stale fixture privileges. Learner dashboards still
need `seed_demo_enrolment.py` -- this script only creates the identities.

    apps/api/.venv/Scripts/python.exe scripts/seed_e2e_accounts.py

Refuses to run unless ENVIRONMENT is local.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import get_settings
from src.core.crypto import CryptoBox
from src.core.db import get_sessionmaker, init_engine, set_tenant
from src.core.security import hash_password
from src.models.rbac import RoleAssignment
from src.models.tenant import Tenant
from src.models.user import User
from src.services import identity

settings = get_settings()

# (env var the spec reads, email, password, role_code, which spec needs it)
ACCOUNTS: list[tuple[str, str, str, str, str]] = [
    (
        "E2E_ADMIN_EMAIL",
        "ops-admin@example.com",
        "SmokeTest123!admin",
        "super_admin",
        "admin.spec.ts",
    ),
    ("E2E_EMAIL", "smoke-agent@example.com", "SmokeTest123!agent", "learner", "learner.spec.ts"),
    (
        "E2E_REFRESH_EMAIL",
        "refresh-admin@example.com",
        "SmokeTest123!refresh",
        "admin",
        "session-refresh.spec.ts",
    ),
    (
        "E2E_SURVEY_ADMIN_EMAIL",
        "survey-admin@example.com",
        "SmokeTest123!survey",
        "content_author",
        "survey-pairing.spec.ts",
    ),
    # super_admin, not content_author: course:edit + course:publish authors
    # the fixture content, but product:manage (needed to price and activate
    # it — 0022 deliberately withholds that from content_author) does not
    # exist on that role. This account is never signed into through the
    # browser — only used via Playwright's `request` context in a
    # `beforeAll`, so it costs one login per file, not one per test.
    (
        "E2E_CONTENT_EMAIL",
        "content-fixture@example.com",
        "SmokeTest123!content",
        "super_admin",
        "learner-assessment.spec.ts, checkout.spec.ts (fixture authoring only)",
    ),
    (
        "E2E_ASSESS_EMAIL",
        "assess-learner@example.com",
        "SmokeTest123!assess",
        "learner",
        "learner-assessment.spec.ts",
    ),
    (
        "E2E_BUYER_EMAIL",
        "checkout-buyer@example.com",
        "SmokeTest123!buyer",
        "",
        "checkout.spec.ts",
    ),
    (
        "E2E_FINANCE_EMAIL",
        "finance-e2e@example.com",
        "SmokeTest123!finance",
        "finance",
        "admin-finance.spec.ts",
    ),
    # A distinct buyer from checkout-buyer@ — admin-finance.spec.ts submits
    # its own EFT payment for finance-e2e@ to approve, and both spec files
    # can run in parallel (fullyParallel: true), so this can't share an
    # account with checkout.spec.ts's buyer any more than either can share
    # a login budget with ops-admin@.
    (
        "E2E_FINANCE_BUYER_EMAIL",
        "finance-buyer-e2e@example.com",
        "SmokeTest123!financebuyer",
        "",
        "admin-finance.spec.ts (fixture purchase only)",
    ),
    (
        "E2E_ORG_EMAIL",
        "org-e2e@example.com",
        "SmokeTest123!orge2e",
        "",
        "organisations.spec.ts",
    ),
]


async def _demo_tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id = (
        await session.execute(select(Tenant.id).where(Tenant.slug == "demo"))
    ).scalar_one_or_none()
    if tenant_id is None:
        raise SystemExit("no 'demo' tenant — run alembic upgrade head first")
    return uuid.UUID(str(tenant_id))


async def _upsert(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    email: str,
    password: str,
    role: str,
) -> str:
    """`role=""` means deliberately roleless — checkout.spec.ts's buyer and
    organisations.spec.ts's org creator both need nothing beyond being
    authenticated (order/payment-proof endpoints gate on order ownership,
    not a permission; creating an organisation is self-service for any
    signed-in user, services/organisations.py)."""
    user = (
        await session.execute(
            select(User).where(User.email_blind_index == crypto.blind_index(email))
        )
    ).scalar_one_or_none()
    if user is None:
        user = await identity.create_user(
            session, crypto, tenant_id=tenant_id, email=email, password=password
        )
        action = "created"
    else:
        # Reset rather than leave it: an account whose password drifted is
        # indistinguishable, at the login form, from one that never existed.
        user.password_hash = hash_password(password)
        user.status = "active"
        user.locked_until = None
        user.failed_login_count = 0
        action = "reset"

    # These are repo-owned local fixtures, so make their authorization
    # deterministic as well as their credentials. An account previously
    # granted super_admin must not silently retain that access when a spec
    # is narrowed to admin or learner.
    await session.execute(
        delete(RoleAssignment).where(
            RoleAssignment.tenant_id == tenant_id,
            RoleAssignment.user_id == user.id,
            RoleAssignment.role_code != role,
        )
    )
    if role:
        existing = (
            await session.execute(
                select(RoleAssignment).where(
                    RoleAssignment.user_id == user.id, RoleAssignment.role_code == role
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(RoleAssignment(tenant_id=tenant_id, user_id=user.id, role_code=role))
            action += " + role granted"
    return action


async def main() -> None:
    if settings.environment not in ("local", "development", "dev"):
        raise SystemExit(f"refusing to seed e2e accounts in ENVIRONMENT={settings.environment!r}")
    crypto = CryptoBox(settings.encryption_key_bytes(), settings.blind_index_key_bytes())
    init_engine(settings)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        tenant_id = await _demo_tenant(session)
        await set_tenant(session, tenant_id)
        for _env, email, password, role, spec in ACCOUNTS:
            action = await _upsert(
                session, crypto, tenant_id=tenant_id, email=email, password=password, role=role
            )
            print(f"{email:28} {role:12} {action:24} ({spec})")
    print(f"done — {len(ACCOUNTS)} accounts on the demo tenant")


asyncio.run(main())
