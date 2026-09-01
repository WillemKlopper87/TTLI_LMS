"""Video pipeline (02 §5.4/5.5/7.3/7.4) — see 0012's migration docstring
for why video_assets/transcode_jobs are global (not tenant-scoped) while
video_progress/video_heartbeats are tenant-scoped, and why
video_heartbeats isn't given the ledger_entries-style two-layer
append-only enforcement despite the "append-only" description in 02 §7.4.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk


class TranscodeJob(Base, TimestampMixin):
    """Mirrors the durable half of the ported TranscodingEngine (06 §3.2):
    state, progress, timestamps. The live process handle never persists —
    processes die, this row survives, and the worker hydrates from it."""

    __tablename__ = "transcode_jobs"

    id: Mapped[uuid.UUID] = pk()
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="pending")
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    processed_seconds: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VideoAsset(Base, TimestampMixin):
    __tablename__ = "video_assets"

    id: Mapped[uuid.UUID] = pk()
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcode_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("transcode_jobs.id", ondelete="SET NULL"), nullable=True
    )
    playlist_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WebVTT, stored under this asset's own video-assets/{id}/ prefix and
    # served through the same signed playback token as HLS segments —
    # see 0015's migration docstring.
    caption_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per rung: height, video kbps, maxrate, bufsize (02 §5.4) — a snapshot
    # of the ladder actually used, since LADDER in services/media/ffmpeg.py
    # could change between this asset's transcode and a later one.
    renditions: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="uploaded")
    # Upload provenance (0040) — captured once at upload time since
    # `StorageService.get_object` has no way to hand content-type back to
    # the caller on read; this is what makes serving the original file
    # as-is possible without guessing a media type from a file extension.
    source_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # {rung: bytes}, computed once from the ffprobe duration against
    # LADDER's bitrates and shown to the admin before they commit to a
    # rung selection (0040) — never re-derived after upload.
    estimated_sizes: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    # The admin's actual choice at finalize time (0040) — read by
    # services/media/pipeline.py instead of the hardcoded DEFAULT_RUNGS.
    # Empty while state="draft" (not yet decided).
    requested_rungs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    # "hls" (transcoded) or "progressive" (as-is bypass, served by
    # GET /media/{id}/original) — 0040.
    delivery_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="hls")
    # Advisory (0040): set from an optional form field at upload time so
    # the tenant->course video-settings chain can be resolved before the
    # admin has decided anything, and re-checked at finalize time so the
    # as-is bypass can't be granted off a client-supplied course id that
    # drifted from what the decision panel actually showed.
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )


class VideoProgress(Base, TimestampMixin):
    """furthest_position_seconds only ever increases (REQ-BYPASS-04's seek
    ceiling); watched_seconds accumulates from validated heartbeats, so it
    cannot exceed wall-clock elapsed time (REQ-BYPASS-03)."""

    __tablename__ = "video_progress"
    __table_args__ = (
        Index("uq_video_progress_enrolment_lesson", "enrolment_id", "lesson_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lessons.id", ondelete="RESTRICT"), nullable=False
    )
    furthest_position_seconds: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    watched_seconds: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    heartbeat_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VideoHeartbeat(Base):
    """Server-assigned timestamps only (REQ-BYPASS-02) — created_at has no
    Python-side default and is never set by the caller; the database
    default is the only source."""

    __tablename__ = "video_heartbeats"
    __table_args__ = (Index("ix_video_heartbeats_enrolment_lesson", "enrolment_id", "lesson_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("enrolments.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lessons.id", ondelete="RESTRICT"), nullable=False
    )
    position_seconds: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    playback_rate: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("1.0")
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = ["TranscodeJob", "VideoAsset", "VideoHeartbeat", "VideoProgress"]
