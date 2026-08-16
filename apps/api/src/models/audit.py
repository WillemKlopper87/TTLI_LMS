"""The audit log.

Append-only, enforced by the database rather than by convention — the migration
adds rules that turn UPDATE and DELETE into no-ops and revokes both privileges.
A correction is a new row.

Failed authorisation attempts are logged too. A learner repeatedly probing
`POST /lessons/{id}/complete` for lessons they have not started is the clearest
bypass signal available.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, pk


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(48), nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Action constants, so a typo in a log call is a NameError rather than a row
# nobody can search for later.
class AuditAction:
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    LOGOUT = "auth.logout"
    TOKEN_REFRESHED = "auth.token.refreshed"  # noqa: S105 - an action name, not a credential
    TOKEN_REUSE_DETECTED = "auth.token.reuse_detected"  # noqa: S105 - ditto
    PASSWORD_CHANGED = "auth.password.changed"  # noqa: S105 - an action name, not a credential
    MFA_ENROLLED = "auth.mfa.enrolled"
    MFA_VERIFIED = "auth.mfa.verified"
    MFA_LOCKED = "auth.mfa.locked"
    AUTHZ_DENIED = "authz.denied"
    TENANT_CREATED = "tenant.created"
    ROLE_ASSIGNED = "rbac.role.assigned"
    ROLE_REVOKED = "rbac.role.revoked"
    LESSON_COMPLETED = "lesson.completed"
    LESSON_COMPLETION_REFUSED = "lesson.completion_refused"
    QUIZ_ATTEMPT_SUBMITTED = "quiz.attempt.submitted"
    SURVEY_RESPONSE_SUBMITTED = "survey.response.submitted"
    ASSIGNMENT_SUBMITTED = "assignment.submitted"
    ASSIGNMENT_REVIEWED = "assignment.reviewed"
    # 03 §5.7: "an invalid signature is 401 and an audit event."
    PAYMENT_WEBHOOK_REJECTED = "payment.webhook.rejected"


__all__ = ["AuditAction", "AuditEvent", "text"]
