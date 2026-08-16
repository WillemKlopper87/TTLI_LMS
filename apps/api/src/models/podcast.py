"""Podcast episodes (REQ-STORE-04, `0026`) — TTLI's own ('authored')
episodes and admin-curated third-party ('curated') recommendations.
Tenant-scoped, unlike `courses` — see `0026`'s migration docstring for why.

Deliberately no `access_level`/gating column — every episode is public by
design (01_PRD.md's own framing: podcasts are "a sales lure"), since no
gated-content unlock mechanism exists anywhere in this codebase yet for
any content type. `state` (the same `ContentState` enum `courses` uses)
is the only visibility gate: draft/in_review/approved/archived episodes
never appear on the public listing, only `published` ones do.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk
from src.models.course import ContentState


class PodcastEpisode(Base, TimestampMixin):
    __tablename__ = "podcast_episodes"
    __table_args__ = (
        Index("uq_podcast_episodes_tenant_slug", "tenant_id", "slug", unique=True),
        Index("ix_podcast_episodes_tenant_state_position", "tenant_id", "state", "position"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # 'authored' (TTLI's own, self-hosted audio) | 'curated' (a
    # third-party episode, embed-only) — validated in services/podcasts.py,
    # not a Postgres enum (0026's docstring explains why).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(ContentState, nullable=False, server_default="draft")

    # 'authored' only.
    show_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    audio_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_image_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Used by both 'authored' (an optional "also on Spotify" cross-post
    # link) and 'curated' (the primary listen path).
    external_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_embed_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 'curated' only — the "recommended by [host]" attribution.
    curator_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    curator_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


__all__ = ["PodcastEpisode"]
