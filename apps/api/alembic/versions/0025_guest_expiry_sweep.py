"""Guest expiry sweep (02 §12.4) — "Downgrade expired guests, retain the
lead," hourly.

This has been a documented, deliberate gap since the guest-access pass:
access itself was already enforced live at the two points that actually
matter (`identity.consume_magic_link`, `tokens.rotate`, both raising on an
expired guest before the request does anything) — this sweep is the
`users.status` bookkeeping half only, so an expired guest reads as
`'expired'` rather than sitting in `'active'` forever with nothing to show
for it. "Retain the lead" needs no extra work here: the sweep never touches
`contacts`/`leads`, only `users.status`, so the lead record this guest
originated from is untouched either way.

`downgrade_expired_guests` follows `0005`'s SECURITY DEFINER
maintenance-function idiom exactly (also `0021`'s `revoke_lapsed_
subscriptions`, the most recent precedent) — the privilege to update across
every tenant despite RLS lives in the function's owner, never in the
worker process, which connects as the same least-privileged `app_user` the
API does. `WHERE status = 'active'` makes a re-run idempotent and means
the returned count is only ever genuinely-new transitions, not a re-count
of everything already `'expired'`.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION downgrade_expired_guests()
        RETURNS int
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            n int;
        BEGIN
            UPDATE users
            SET status = 'expired'
            WHERE is_guest
              AND status = 'active'
              AND guest_expires_at IS NOT NULL
              AND guest_expires_at < now();
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END;
        $$;
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION downgrade_expired_guests() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION downgrade_expired_guests() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS downgrade_expired_guests()")
