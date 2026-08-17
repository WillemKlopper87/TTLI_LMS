"""Recommendations (`0031`) — a short external "further reading" link with
a one-line editorial note. See the model this was split out from,
`PodcastEpisode`'s `kind == "curated"` rows, and that module's own
docstring for why a recommendation is not shaped like an episode.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk
from src.models.course import ContentState


class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_tenant_state_position", "tenant_id", "state", "position"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    curator_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    curator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(ContentState, nullable=False, server_default="draft")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


__all__ = ["Recommendation"]
