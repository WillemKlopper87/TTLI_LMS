"""The arq worker.

Run with:  arq src.workers.main.WorkerSettings   (from apps/api)

Both maintenance jobs are thin wrappers over SECURITY DEFINER SQL functions
installed by migration 0005 — the privilege to create partitions or delete
across tenants lives in the database function's owner, never in this
process, which connects as the same least-privileged app_user as the API.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq import func
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import select, text

from src.core.config import get_settings
from src.core.db import dispose_engine, get_sessionmaker, init_engine, set_tenant
from src.core.logging import configure_logging, get_logger
from src.models.audit import AuditAction
from src.models.push import PushSubscription
from src.models.rbac import RoleAssignment, RolePermission
from src.models.user import User
from src.services import audit
from src.services import push as push_service
from src.services.email import send_sync
from src.services.media.pipeline import transcode_video_asset
from src.services.storage import get_storage_adapter

log = get_logger(__name__)


async def extend_event_partitions(ctx: dict[str, Any]) -> int:
    """Keep ~12 months of events partitions ahead of now. Idempotent."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        created = (await session.execute(text("SELECT extend_events_partitions(12)"))).scalar_one()
    log.info("events_partitions_extended", created=created)
    return int(created)


async def purge_expired_auth(ctx: dict[str, Any]) -> int:
    """Delete refresh tokens, magic links and password resets whose expiry is
    more than 30 days past. The grace period keeps recent rows available to
    the reuse-detection path and for incident forensics."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        purged = (await session.execute(text("SELECT purge_expired_auth_rows(30)"))).scalar_one()
    log.info("expired_auth_rows_purged", purged=purged)
    return int(purged)


async def prune_idempotency_keys(ctx: dict[str, Any]) -> int:
    """Retention sweep for `idempotency_keys` (03 §1.6, 0032).

    Two kinds of row age out (both handled inside the SECURITY DEFINER
    function — the worker holds no tenant GUC, so a plain DELETE would
    see zero rows through RLS, same reason purge_expired_auth works the
    way it does):
    - completed replays older than 30 days — matching purge_expired_auth's
      forensic grace period; a client replaying a payment key later than
      that re-executes, and the business layer's own double-refund /
      already-approved guards are what protect it then (the exact window
      is one of 03 §13's named open questions);
    - dead in-flight reservations older than 1 day — normally released by
      the middleware itself or taken over by a retry; this catches ones
      whose caller never came back.
    """
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        pruned = (await session.execute(text("SELECT prune_idempotency_keys(30, 1)"))).scalar_one()
    log.info("idempotency_keys_pruned", pruned=pruned)
    return int(pruned)


async def revoke_lapsed_subscriptions(ctx: dict[str, Any]) -> int:
    """Formal bookkeeping closure for lapsed subscriptions — access itself
    already lapses live the moment an entitlement's `expires_at` (which
    already has services/subscriptions.py::GRACE_DAYS baked in) passes;
    this just flips `Subscription.status` to 'cancelled' and marks the
    entitlement `revoked_at` so records don't sit in a stale 'active'
    state indefinitely."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        revoked = (
            await session.execute(text("SELECT revoke_lapsed_subscriptions(3)"))
        ).scalar_one()
    log.info("lapsed_subscriptions_revoked", revoked=revoked)
    return int(revoked)


async def downgrade_expired_guests(ctx: dict[str, Any]) -> int:
    """02 §12.4's hourly guest-expiry sweep — `users.status` bookkeeping
    only. Access itself already lapses live at the two points that
    actually gate it (magic-link consumption, refresh rotation, both in
    services/identity.py and services/tokens.py) — this just makes an
    expired guest read as `'expired'` rather than sitting in `'active'`
    with nothing to show for it. Never touches `contacts`/`leads`, so the
    lead this guest originated from is retained either way."""
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        downgraded = (await session.execute(text("SELECT downgrade_expired_guests()"))).scalar_one()
    log.info("expired_guests_downgraded", downgraded=downgraded)
    return int(downgraded)


async def send_push_job(
    ctx: dict[str, Any],
    *,
    tenant_id: str,
    subscription_id: str,
    title: str,
    body: str,
    url: str | None,
) -> bool:
    """Raises on a genuine delivery failure so arq retries with backoff
    (max_tries below) — the same reasoning `send_email_job` already
    established. A dead subscription (404/410) is different: not a
    transient failure to retry, so the row is deleted and the job
    succeeds with `False` rather than being retried against an endpoint
    that will never accept another push."""
    settings = get_settings()
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        await set_tenant(session, uuid.UUID(tenant_id))
        subscription = await session.get(PushSubscription, uuid.UUID(subscription_id))
        if subscription is None:
            return False
        try:
            await asyncio.to_thread(
                push_service.send_push_sync,
                settings,
                endpoint=subscription.endpoint,
                p256dh_key=subscription.p256dh_key,
                auth_key=subscription.auth_key,
                title=title,
                body=body,
                url=url,
            )
        except push_service.PushSubscriptionGone:
            await session.delete(subscription)
            log.info("push_subscription_gone", subscription_id=subscription_id)
            return False
    log.info("push_sent", subscription_id=subscription_id)
    return True


async def send_workshop_reminders(ctx: dict[str, Any]) -> int:
    """The third of the product owner's three push triggers. `due_
    workshop_reminders()` (SECURITY DEFINER, `0027`) atomically finds
    `registered` bookings for sessions starting within 24h that haven't
    been reminded yet, marks them reminded, and returns who to notify —
    marking and notifying can't drift apart, since a crash between the
    two isn't possible (one SQL statement did both). This function's own
    job is just the per-row fan-out into `push.notify_user`, which needs
    a tenant-bound session `due_workshop_reminders()` itself can't hold
    (SECURITY DEFINER intentionally has none — see 0027's docstring)."""
    factory = get_sessionmaker()
    # session.begin() here is load-bearing, not boilerplate: without an
    # explicit commit, due_workshop_reminders()'s own UPDATE ... RETURNING
    # rolls back when the session just closes, so the SELECT half's
    # result looks right in this same transaction while the "mark
    # reminded" half silently never persists — caught by this function's
    # own idempotency test asserting a second run finds nothing new.
    async with factory() as lookup_session, lookup_session.begin():
        due = (await lookup_session.execute(text("SELECT * FROM due_workshop_reminders(24)"))).all()
    for row in due:
        async with factory() as session, session.begin():
            await set_tenant(session, row.tenant_id)
            await push_service.notify_user(
                session,
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                title="Workshop starting soon",
                body=f'"{row.workshop_title}" starts at {row.starts_at:%Y-%m-%d %H:%M %Z}.',
            )
    log.info("workshop_reminders_sent", count=len(due))
    return len(due)


async def send_eft_ageing_alerts(ctx: dict[str, Any]) -> int:
    """02 §12.4's daily EFT ageing alert (BACKLOG.md R4) — until this job
    existed, nothing computed "an approval has been pending too long", so
    a growing manual-approval backlog had no way to surface itself
    (`docs/research/bank-eft-automation.md` names this exact signal as
    the trigger to revisit EFT automation).

    `due_eft_ageing_alerts()` (SECURITY DEFINER, 0034) atomically flags
    each order once and returns it — same one-statement mark-and-return
    shape `due_workshop_reminders()` established, for the same "can't
    mark without also acting on it" reason. Unlike that function, this
    one deliberately does *not* also resolve who to notify: an audit
    event is written for every returned order regardless (the durable,
    always-fires signal), and only the push fan-out below depends on a
    tenant actually having someone in `payment:approve` — best-effort on
    top of the record, not the record itself."""
    factory = get_sessionmaker()
    async with factory() as lookup_session, lookup_session.begin():
        due = (await lookup_session.execute(text("SELECT * FROM due_eft_ageing_alerts(48)"))).all()

    for row in due:
        async with factory() as session, session.begin():
            await set_tenant(session, row.tenant_id)
            hours_waiting = int((datetime.now(UTC) - row.updated_at).total_seconds() // 3600)
            await audit.record(
                session,
                tenant_id=row.tenant_id,
                action=AuditAction.PAYMENT_AGEING_ALERTED,
                entity_type="order",
                entity_id=row.order_id,
                after={
                    "payment_reference": row.payment_reference,
                    "hours_waiting": hours_waiting,
                },
            )
            approvers = (
                (
                    await session.execute(
                        select(RoleAssignment.user_id)
                        .join(RolePermission, RolePermission.role_code == RoleAssignment.role_code)
                        .join(User, User.id == RoleAssignment.user_id)
                        .where(
                            RoleAssignment.tenant_id == row.tenant_id,
                            RolePermission.permission_code == "payment:approve",
                            User.status == "active",
                        )
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            for user_id in approvers:
                await push_service.notify_user(
                    session,
                    tenant_id=row.tenant_id,
                    user_id=user_id,
                    title="An EFT/PO approval is ageing",
                    body=(
                        f"Payment reference {row.payment_reference or str(row.order_id)[:8]} has "
                        f"been awaiting approval for over {hours_waiting}h."
                    ),
                )
    log.info("eft_ageing_alerts_sent", count=len(due))
    return len(due)


async def send_email_job(ctx: dict[str, Any], *, to: str, subject: str, body: str) -> None:
    """Raises on any SMTP failure so arq retries with backoff (max_tries
    below) instead of the message being silently dropped — the one thing
    services/email.py's old fire-and-forget swallow could never do."""
    settings = get_settings()
    await asyncio.to_thread(send_sync, settings, to=to, subject=subject, body=body)
    log.info("email_sent", to_domain=to.rsplit("@", 1)[-1])


async def transcode_video_job(ctx: dict[str, Any], *, video_asset_id: str) -> None:
    """The long-running half of the media pipeline (06 §3.2) — ffmpeg is a
    blocking subprocess, so this runs off the request path entirely,
    matching how send_email_job already keeps SMTP off it."""
    settings = get_settings()
    factory = get_sessionmaker()
    storage = get_storage_adapter(settings)
    # No session.begin() wrapper — transcode_video_asset commits at
    # multiple points itself (progress updates, then the final state), not
    # once at the end, which session.begin()'s single-commit-on-exit
    # contract doesn't fit.
    async with factory() as session:
        await transcode_video_asset(
            session, storage, settings, video_asset_id=uuid.UUID(video_asset_id)
        )
    log.info("transcode_job_finished", video_asset_id=video_asset_id)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.environment == "local")
    init_engine(settings)
    log.info("worker_started", environment=settings.environment)


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        extend_event_partitions,
        purge_expired_auth,
        prune_idempotency_keys,
        revoke_lapsed_subscriptions,
        downgrade_expired_guests,
        func(send_email_job, max_tries=5),
        func(send_push_job, max_tries=5),
        # max_tries=1: a failed transcode already leaves video_assets/
        # transcode_jobs in a clean 'failed' state with the real error
        # (pipeline.py's except clause) — a bare retry would just re-run
        # the same doomed ffmpeg invocation.
        func(transcode_video_job, max_tries=1),
        send_workshop_reminders,
        send_eft_ageing_alerts,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        # Partitions monthly on the 1st; 0004 bootstrapped ~13 months of
        # runway, so a missed run is survivable for a long time.
        cron(extend_event_partitions, day=1, hour=2, minute=0),
        cron(purge_expired_auth, hour=3, minute=30),
        cron(prune_idempotency_keys, hour=3, minute=45),
        cron(revoke_lapsed_subscriptions, hour=4, minute=0),
        # Hourly per 02 §12.4, not daily like the other sweeps above — a
        # guest's whole access window is measured in days (settings.
        # guest_access_days, default 7), so a once-a-day cadence would
        # leave the status bookkeeping visibly stale for up to 24h.
        cron(downgrade_expired_guests, minute=0),
        # Every 15 minutes, not hourly: the reminder window itself is 24h
        # (due_workshop_reminders' default), so a coarser cadence would
        # only widen how late a reminder can arrive relative to when a
        # session first entered the window, not how often the sweep runs
        # relative to the sessions it actually finds.
        cron(send_workshop_reminders, minute={0, 15, 30, 45}),
        # Daily per 02 §12.4's own table; same off-peak hour band as the
        # other daily sweeps above.
        cron(send_eft_ageing_alerts, hour=4, minute=15),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


__all__ = [
    "WorkerSettings",
    "downgrade_expired_guests",
    "extend_event_partitions",
    "prune_idempotency_keys",
    "purge_expired_auth",
    "revoke_lapsed_subscriptions",
    "send_eft_ageing_alerts",
    "send_email_job",
    "send_push_job",
    "send_workshop_reminders",
    "transcode_video_job",
]
