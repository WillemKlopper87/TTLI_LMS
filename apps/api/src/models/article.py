"""Articles (`0030`) — long-form written content, tenant-scoped like
`podcast_episodes` (see that model's own docstring for why tenant-scoped
rather than global like `courses`). No curriculum, no completion rules,
no pricing — this is marketing/thought-leadership content, not a product.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk
from src.models.course import ContentState


class Article(Base, TimestampMixin):
    __tablename__ = "articles"
    __table_args__ = (
        Index("uq_articles_tenant_slug", "tenant_id", "slug", unique=True),
        Index("ix_articles_tenant_state_position", "tenant_id", "state", "position"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    cover_image_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(ContentState, nullable=False, server_default="draft")
    # Set on the transition to published, not on create — see
    # services/articles.py.publish_article. Distinct from created_at,
    # since a draft can sit for weeks before it goes live.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Computed at publish time from a ~200wpm heuristic.
    reading_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


__all__ = ["Article"]
