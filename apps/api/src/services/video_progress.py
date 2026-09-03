"""Server-side video-watch validation (03 §6.3, REQ-BYPASS-02/03/04).

None of this exists in the ported Streaming_Server pipeline (06 §3.4) —
it's new, built for this platform specifically. Every rule here is one
the client cannot talk its way around because the server, not the
client, is the only thing that ever writes these values:

- REQ-BYPASS-02: `created_at`/`last_heartbeat_at` are server-assigned:
  the request body carries no timestamp field at all, so there's nothing
  for a client to lie about.
- REQ-BYPASS-03: `watched_seconds` grows by at most the server-measured
  interval since the previous heartbeat, capped per heartbeat — a 0% to
  100% jump is impossible no matter what position a single request claims.
- REQ-BYPASS-04: `position_seconds` beyond the furthest one legitimately
  reached (plus a small buffering-jitter tolerance) is refused outright.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.core.ids import uuid7
from src.models.media import VideoHeartbeat, VideoProgress

SEEK_TOLERANCE_SECONDS = Decimal("2")
# 03 §13 leaves the real heartbeat interval an open question. This caps
# what a single heartbeat can add to watched_seconds regardless of how
# long the actual gap since the last one was — a paused tab or a dropped
# connection must not be replayable as watched time once it reconnects.
HEARTBEAT_MAX_INTERVAL_SECONDS = Decimal("30")


class SeekNotPermitted(AppError):
    status_code = 400
    code = "SEEK_NOT_PERMITTED"


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    furthest_position_seconds: Decimal
    watched_seconds: Decimal


async def record_heartbeat(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    enrolment_id: uuid.UUID,
    lesson_id: uuid.UUID,
    lesson_block_id: uuid.UUID,
    position_seconds: Decimal,
    playback_rate: Decimal,
    session_id: str,
    max_playback_rate: Decimal,
) -> HeartbeatResult:
    """Keyed by `lesson_block_id`, not `lesson_id` (0041) — a lesson can
    hold more than one video block, and heartbeats from two different
    ones must not collide into the same progress row. `lesson_id` is
    still recorded (not part of the identity key) since some queries
    still want "every progress row in this lesson" without a join."""
    if playback_rate <= 0 or playback_rate > max_playback_rate:
        raise AppError(f"Playback rate {playback_rate} is out of the permitted range.")

    # H-6: locked for the rest of this function. Without FOR UPDATE, N
    # heartbeats landing concurrently for the same (enrolment, block) all
    # read the same last_heartbeat_at and each independently compute up
    # to HEARTBEAT_MAX_INTERVAL_SECONDS of "elapsed" — watched_seconds
    # grows by N x the real wall-clock gap instead of once. Locking the
    # row serialises them, mirroring services/workshops/booking.py's
    # FOR UPDATE idiom for concurrency-safe accounting: the second
    # request only proceeds once the first has committed its advanced
    # last_heartbeat_at, at which point its own elapsed collapses to
    # ~0s, same as two genuinely sequential heartbeats would.
    stmt = (
        select(VideoProgress)
        .where(
            VideoProgress.enrolment_id == enrolment_id,
            VideoProgress.lesson_block_id == lesson_block_id,
        )
        .with_for_update()
    )
    progress = (await session.execute(stmt)).scalar_one_or_none()
    now = datetime.now(UTC)

    if progress is None:
        progress = VideoProgress(
            id=uuid7(),
            tenant_id=tenant_id,
            enrolment_id=enrolment_id,
            lesson_id=lesson_id,
            lesson_block_id=lesson_block_id,
        )
        session.add(progress)
        await session.flush()

    if position_seconds > progress.furthest_position_seconds + SEEK_TOLERANCE_SECONDS:
        raise SeekNotPermitted(
            "That position is beyond what this session has legitimately watched.",
            {"furthest_position_seconds": str(progress.furthest_position_seconds)},
        )

    elapsed = Decimal("0")
    if progress.last_heartbeat_at is not None:
        raw_elapsed = Decimal(str((now - progress.last_heartbeat_at).total_seconds()))
        wall_clock_elapsed = max(Decimal("0"), min(raw_elapsed, HEARTBEAT_MAX_INTERVAL_SECONDS))
        # H-6: also bound by what the *reported position* makes plausible
        # — without this, calling this endpoint repeatedly at the same
        # (or an earlier) position, e.g. while genuinely paused, still
        # added up to HEARTBEAT_MAX_INTERVAL_SECONDS of watched time per
        # call regardless of whether playback ever advanced. A forward
        # move of `position_delta` seconds, at this heartbeat's own
        # playback_rate, plausibly took `position_delta / playback_rate`
        # wall-clock seconds; SEEK_TOLERANCE_SECONDS' worth of slack
        # covers ordinary buffering/timer jitter on top of that, not
        # extra "free" watched time. `last_position_seconds` is None only
        # on this row's first-ever heartbeat, where `elapsed` is already
        # forced to 0 above (this branch requires last_heartbeat_at to be
        # set, and the two columns are always written together below) —
        # the fallback here is defensive, not a path this code takes.
        if progress.last_position_seconds is None:
            plausible_elapsed = wall_clock_elapsed
        else:
            position_delta = position_seconds - progress.last_position_seconds
            plausible_elapsed = (
                max(Decimal("0"), position_delta) / playback_rate + SEEK_TOLERANCE_SECONDS
            )
        elapsed = min(wall_clock_elapsed, plausible_elapsed)

    progress.watched_seconds = progress.watched_seconds + elapsed
    progress.furthest_position_seconds = max(progress.furthest_position_seconds, position_seconds)
    progress.last_position_seconds = position_seconds
    progress.heartbeat_count += 1
    progress.last_heartbeat_at = now

    session.add(
        VideoHeartbeat(
            id=uuid7(),
            tenant_id=tenant_id,
            enrolment_id=enrolment_id,
            lesson_id=lesson_id,
            lesson_block_id=lesson_block_id,
            position_seconds=position_seconds,
            playback_rate=playback_rate,
            session_id=session_id,
        )
    )
    await session.flush()

    return HeartbeatResult(
        furthest_position_seconds=progress.furthest_position_seconds,
        watched_seconds=progress.watched_seconds,
    )


async def watch_percentage(
    session: AsyncSession,
    *,
    enrolment_id: uuid.UUID,
    lesson_block_id: uuid.UUID,
    duration_seconds: int,
) -> float | None:
    """Feeds `completion_rules.video_watch_percentage` (services/completion.py).
    None when no progress row exists yet or the asset has no known
    duration — the caller treats that as "not met", never as 100%."""
    if duration_seconds <= 0:
        return None
    stmt = select(VideoProgress.watched_seconds).where(
        VideoProgress.enrolment_id == enrolment_id,
        VideoProgress.lesson_block_id == lesson_block_id,
    )
    watched = (await session.execute(stmt)).scalar_one_or_none()
    if watched is None:
        return None
    return min(100.0, float(watched) / duration_seconds * 100)


__all__ = ["HeartbeatResult", "SeekNotPermitted", "record_heartbeat", "watch_percentage"]
