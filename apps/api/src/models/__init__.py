"""Model package.

Every model must be imported here. Alembic's autogenerate compares against
`Base.metadata`, and a model that is never imported is invisible to it — which
is how `alembic check` starts passing while the schema quietly drifts.
"""

from src.models.assessment import (
    Assignment,
    AssignmentSubmission,
    Quiz,
    QuizAnswer,
    QuizAttempt,
    QuizQuestion,
    Survey,
    SurveyQuestion,
    SurveyResponse,
    SurveyResponseMode,
)
from src.models.audit import AuditAction, AuditEvent
from src.models.auth import MagicLink, MfaRecoveryCode, PasswordReset, RefreshToken
from src.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin
from src.models.commerce import (
    Entitlement,
    Invoice,
    InvoiceItem,
    InvoiceNumberCounter,
    LedgerEntry,
    Order,
    OrderItem,
    Payment,
    Price,
    Product,
    TaxRule,
)
from src.models.consent import ConsentRecord
from src.models.contact import Contact
from src.models.course import (
    AccessLevel,
    Course,
    CourseTenantAssignment,
    Lesson,
    ManagerVisibility,
    Module,
)
from src.models.credential import (
    Badge,
    BadgeTemplate,
    Certificate,
    CertificateTemplate,
    CredentialStatus,
    CredentialVerification,
)
from src.models.event import Event
from src.models.lead import Lead
from src.models.learning import Enrolment, LessonCompletion, LessonState
from src.models.media import TranscodeJob, VideoAsset, VideoHeartbeat, VideoProgress
from src.models.organisation import Organisation, OrganisationMember
from src.models.rbac import Permission, Role, RoleAssignment, RolePermission
from src.models.tenant import Tenant, TenantDomain
from src.models.theme import TenantTheme
from src.models.user import User
from src.models.workshop import (
    AttendanceRecord,
    AttendanceStatus,
    Booking,
    BookingStatus,
    Facilitator,
    FacilitatorAvailability,
    MeetingLink,
    MeetingProvider,
    Workshop,
    WorkshopSession,
    WorkshopSessionStatus,
    WorkshopSessionType,
)

__all__ = [
    "AccessLevel",
    "Assignment",
    "AssignmentSubmission",
    "AttendanceRecord",
    "AttendanceStatus",
    "AuditAction",
    "AuditEvent",
    "Badge",
    "BadgeTemplate",
    "Base",
    "Booking",
    "BookingStatus",
    "Certificate",
    "CertificateTemplate",
    "ConsentRecord",
    "Contact",
    "Course",
    "CourseTenantAssignment",
    "CredentialStatus",
    "CredentialVerification",
    "Enrolment",
    "Entitlement",
    "Event",
    "Facilitator",
    "FacilitatorAvailability",
    "Invoice",
    "InvoiceItem",
    "InvoiceNumberCounter",
    "Lead",
    "LedgerEntry",
    "Lesson",
    "LessonCompletion",
    "LessonState",
    "MagicLink",
    "ManagerVisibility",
    "MeetingLink",
    "MeetingProvider",
    "MfaRecoveryCode",
    "Module",
    "Order",
    "OrderItem",
    "Organisation",
    "OrganisationMember",
    "PasswordReset",
    "Payment",
    "Permission",
    "Price",
    "Product",
    "Quiz",
    "QuizAnswer",
    "QuizAttempt",
    "QuizQuestion",
    "RefreshToken",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "SoftDeleteMixin",
    "Survey",
    "SurveyQuestion",
    "SurveyResponse",
    "SurveyResponseMode",
    "TaxRule",
    "Tenant",
    "TenantDomain",
    "TenantMixin",
    "TenantTheme",
    "TimestampMixin",
    "TranscodeJob",
    "User",
    "VideoAsset",
    "VideoHeartbeat",
    "VideoProgress",
    "Workshop",
    "WorkshopSession",
    "WorkshopSessionStatus",
    "WorkshopSessionType",
]
