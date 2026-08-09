"""Sprint 3: first-party analytics events, partitioned monthly.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"

# One month back through twelve months ahead of whatever month this migration
# actually runs in. Extending the range further is a scheduled job
# (02_DATA_MODEL.md §12.4) that belongs in src/workers once arq is wired up
# (Sprint 4+) — this only bootstraps enough runway for Phase 1 to demo on.
PAST_MONTHS = 1
FUTURE_MONTHS = 12


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = month - 1 + delta
    return year + zero_based // 12, zero_based % 12 + 1


def _partition_name(year: int, month: int) -> str:
    return f"events_{year:04d}_{month:02d}"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE events (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            anonymous_id UUID NOT NULL,
            user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            session_id UUID NULL,
            event_name VARCHAR(128) NOT NULL,
            event_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
            utm_source TEXT NULL,
            utm_medium TEXT NULL,
            utm_campaign TEXT NULL,
            utm_content TEXT NULL,
            utm_term TEXT NULL,
            referrer TEXT NULL,
            locale VARCHAR(16) NULL,
            country VARCHAR(2) NULL,
            device_type VARCHAR(20) NULL,
            consent_marketing BOOLEAN NOT NULL,
            consent_analytics BOOLEAN NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    # No ONLY: an index created directly on a partitioned table this way is
    # inherited by every existing partition and auto-applied to every future
    # one attached afterward — no per-partition index maintenance needed.
    op.execute("CREATE INDEX ix_events_tenant_created ON events (tenant_id, created_at)")
    op.execute("CREATE INDEX ix_events_tenant_event_name ON events (tenant_id, event_name)")
    op.execute("CREATE INDEX ix_events_anonymous_id ON events (anonymous_id)")
    op.execute("CREATE INDEX ix_events_user_id ON events (user_id)")
    op.execute("CREATE INDEX ix_events_session_id ON events (session_id)")

    op.execute("ALTER TABLE events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON events
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON events TO {APP_ROLE}")

    today = datetime.datetime.now(tz=datetime.UTC).date()
    year, month = _add_months(today.year, today.month, -PAST_MONTHS)
    for _ in range(PAST_MONTHS + FUTURE_MONTHS + 1):
        start_year, start_month = year, month
        end_year, end_month = _add_months(year, month, 1)
        name = _partition_name(start_year, start_month)
        op.execute(
            f"""
            CREATE TABLE {name} PARTITION OF events
            FOR VALUES FROM ('{start_year:04d}-{start_month:02d}-01')
                        TO ('{end_year:04d}-{end_month:02d}-01')
            """
        )
        year, month = end_year, end_month


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON events")
    # DROP TABLE on a partitioned parent drops every partition with it — they
    # are not independent objects that need dropping first.
    op.execute("DROP TABLE IF EXISTS events")
