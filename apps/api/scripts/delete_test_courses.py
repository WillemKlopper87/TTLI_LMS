"""Hard-delete specific test/diagnostic courses and everything that hangs
off them (modules, lessons, blocks, enrolments, orders, products, prices,
tenant assignments, entitlements).

Unlike `hide_test_courses.py` (which un-assigns test artifacts from the
demo tenant, reversibly, for the ~1,300-row historical test-run buildup),
this is for a small, explicitly-named set of throwaway courses -- e.g. the
ones a diagnostic/manual session just created -- where genuine removal
(not hiding) is what's wanted. Pass course slugs or ids on the command
line; nothing is matched by pattern.

Connects with the `DATABASE_URL_SYNC` admin credential (the `ttli`
bootstrap role, not `app_user`), deliberately: `app_user` has no DELETE
grant on several of these tables (payments/invoices/refunds/entitlements
are append-only by design at the grant level -- confirmed by hitting
`InsufficientPrivilegeError` while first drafting this against the app's
own engine). That restriction is a real security control the app should
never bypass at runtime; this script is a one-off ops action, run by a
human, not application code, so using the admin role here is correct, not
a workaround.

Deletion order respects this schema's FK graph (`courses` cascades to
`modules` -> `lessons` -> `lesson_blocks`, but `course_tenant_assignments`,
`enrolments`, `products`, `subscription_plan_courses` and
`learning_path_courses` all RESTRICT on `course_id`, several tables chain
off `orders`/`products` the same way, and `enrolments.entitlement_id` ->
`entitlements.id` is RESTRICT too -- enrolments must be deleted *before*
entitlements, not after, which the first version of this script got
backwards and PostgreSQL correctly refused). Reproduce with:

    SELECT tc.table_name, ccu.table_name AS foreign_table, rc.delete_rule
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu USING (constraint_name)
    JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
    JOIN information_schema.referential_constraints rc USING (constraint_name)
    WHERE tc.constraint_type = 'FOREIGN KEY';

Dry run by default:

    apps/api/.venv/Scripts/python.exe scripts/delete_test_courses.py <slug-or-id> [...]

Apply it:

    apps/api/.venv/Scripts/python.exe scripts/delete_test_courses.py --apply <slug-or-id> [...]

Local/dev only; refuses to run against a production environment.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg
from src.core.config import get_settings


def _admin_dsn(sync_url: str) -> str:
    # asyncpg wants a plain postgresql:// URL, not SQLAlchemy's
    # postgresql+psycopg2:// dialect prefix.
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


async def _resolve_course_ids(conn: asyncpg.Connection, targets: list[str]) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for target in targets:
        try:
            ids.append(uuid.UUID(target))
            continue
        except ValueError:
            pass
        row = await conn.fetchrow("SELECT id FROM courses WHERE slug = $1", target)
        if row is None:
            raise SystemExit(f"no course with slug or id {target!r}")
        ids.append(row["id"])
    return ids


async def main() -> None:
    apply = "--apply" in sys.argv
    targets = [a for a in sys.argv[1:] if a != "--apply"]
    if not targets:
        raise SystemExit("usage: delete_test_courses.py [--apply] <slug-or-id> [...]")

    settings = get_settings()
    if settings.environment not in ("local", "development", "dev"):
        raise SystemExit(f"refusing to run in ENVIRONMENT={settings.environment!r}")

    conn = await asyncpg.connect(_admin_dsn(settings.sync_database_url))
    try:
        tx = conn.transaction()
        await tx.start()
        try:
            course_ids = await _resolve_course_ids(conn, targets)
            titles = await conn.fetch(
                "SELECT slug, title FROM courses WHERE id = ANY($1::uuid[])", course_ids
            )
            print("target courses:")
            for row in titles:
                print(f"  - {row['title']} ({row['slug']})")

            product_ids = [
                r["id"]
                for r in await conn.fetch(
                    "SELECT id FROM products WHERE course_id = ANY($1::uuid[])", course_ids
                )
            ]
            order_ids = [
                r["order_id"]
                for r in await conn.fetch(
                    "SELECT DISTINCT order_id FROM order_items WHERE product_id = ANY($1::uuid[])",
                    product_ids,
                )
            ]
            enrolment_count = await conn.fetchval(
                "SELECT count(*) FROM enrolments WHERE course_id = ANY($1::uuid[])", course_ids
            )

            print(f"products     : {len(product_ids)}")
            print(f"orders       : {len(order_ids)}")
            print(f"enrolments   : {enrolment_count}")

            if not apply:
                print()
                print("DRY RUN -- nothing changed. Re-run with --apply to delete.")
                await tx.rollback()
                return

            await conn.execute("DELETE FROM refunds WHERE order_id = ANY($1::uuid[])", order_ids)
            await conn.execute("DELETE FROM payments WHERE order_id = ANY($1::uuid[])", order_ids)
            await conn.execute("DELETE FROM invoices WHERE order_id = ANY($1::uuid[])", order_ids)

            # enrolments before entitlements -- enrolments.entitlement_id
            # RESTRICTs on entitlements.id.
            await conn.execute(
                "DELETE FROM enrolments WHERE course_id = ANY($1::uuid[])", course_ids
            )
            await conn.execute(
                "DELETE FROM entitlements WHERE source_order_id = ANY($1::uuid[])", order_ids
            )
            await conn.execute(
                "DELETE FROM entitlements WHERE target_id = ANY($1::uuid[])", course_ids
            )

            await conn.execute("DELETE FROM orders WHERE id = ANY($1::uuid[])", order_ids)

            await conn.execute(
                "DELETE FROM subscription_plans WHERE product_id = ANY($1::uuid[])", product_ids
            )
            await conn.execute("DELETE FROM prices WHERE product_id = ANY($1::uuid[])", product_ids)
            await conn.execute("DELETE FROM products WHERE id = ANY($1::uuid[])", product_ids)

            await conn.execute(
                "DELETE FROM course_tenant_assignments WHERE course_id = ANY($1::uuid[])",
                course_ids,
            )
            await conn.execute(
                "DELETE FROM subscription_plan_courses WHERE course_id = ANY($1::uuid[])",
                course_ids,
            )
            await conn.execute(
                "DELETE FROM learning_path_courses WHERE course_id = ANY($1::uuid[])", course_ids
            )

            await conn.execute("DELETE FROM courses WHERE id = ANY($1::uuid[])", course_ids)

            await tx.commit()
            print()
            print(f"APPLIED -- {len(course_ids)} course(s) and all dependent rows deleted")
        except Exception:
            await tx.rollback()
            raise
    finally:
        await conn.close()


asyncio.run(main())
