"""Idempotency keys become reservations (03 §1.6, `core/idempotency.py`).

The middleware used to store a key only *after* the handler committed —
three separate transactions, so two concurrent replays could both miss
the lookup, both execute the side effect, and the loser then hit the
unique index with a 500 after its duplicate order was already durable.
The fix inverts the order: the key row is INSERTed as an in-flight
reservation (`response_status` NULL) *before* the handler runs, letting
`uq_idempotency_keys_scope` serialise concurrent replays, and is UPDATEd
with the response afterwards — or DELETEd when the attempt died (5xx),
so a transient failure never poisons the key.

Two schema consequences:
- `response_status` must accept NULL, the in-flight marker.
- `app_user` needs UPDATE (record the response) and DELETE (release a
  dead reservation; the worker's retention sweep) — 0023 granted only
  SELECT, INSERT because rows used to be written once, complete. The
  0020/0022 precedent applies: a GRANT must cover every verb the service
  layer actually issues.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

APP_ROLE = "app_user"


def upgrade() -> None:
    op.alter_column(
        "idempotency_keys",
        "response_status",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute(f"GRANT UPDATE, DELETE ON idempotency_keys TO {APP_ROLE}")

    # The worker's retention sweep runs with no tenant GUC set, so RLS
    # (correctly) shows it zero rows — cross-tenant maintenance goes
    # through a SECURITY DEFINER function instead, exactly like 0005's
    # purge_expired_auth_rows. Two windows: completed replays keep a
    # forensic grace period; a dead in-flight reservation only needs to
    # outlive any plausible takeover/retry.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prune_idempotency_keys(
            completed_days int DEFAULT 30, inflight_days int DEFAULT 1
        )
        RETURNS int
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        DECLARE
            n int;
        BEGIN
            DELETE FROM idempotency_keys
            WHERE (response_status IS NOT NULL
                   AND created_at < now() - make_interval(days => completed_days))
               OR (response_status IS NULL
                   AND created_at < now() - make_interval(days => inflight_days));
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END;
        $$;
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION prune_idempotency_keys(int, int) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION prune_idempotency_keys(int, int) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS prune_idempotency_keys(int, int)")
    op.execute(f"REVOKE UPDATE, DELETE ON idempotency_keys FROM {APP_ROLE}")
    # In-flight reservations cannot survive a schema where the column is
    # NOT NULL; they represent requests that never recorded a response,
    # so discarding them (making those keys retryable) is the faithful
    # translation, not data loss.
    op.execute("DELETE FROM idempotency_keys WHERE response_status IS NULL")
    op.alter_column(
        "idempotency_keys",
        "response_status",
        existing_type=sa.Integer(),
        nullable=False,
    )
