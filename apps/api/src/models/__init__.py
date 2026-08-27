"""Model package.

Every model must be imported here. Alembic's autogenerate compares against
`Base.metadata`, and a model that is never imported is invisible to it — which
is how `alembic check` starts passing while the schema quietly drifts.
"""

from src.models.article import Article
from src.models.assessment import (
    Assignment,
    AssignmentSubmission,
    QuestionBankItem,
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
    CreditNote,
    Entitlement,
    Invoice,
    InvoiceItem,
    InvoiceNumberCounter,
    LedgerEntry,
    Order,
    OrderItem,
    Payment,
    PaymentWebhook,
    Price,
    Product,
    Refund,
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
from src.models.crm import (
    Activity,
    Campaign,
    CampaignStatus,
    Deal,
    DealStage,
    EmailEvent,
    EmailSend,
    EmailSendStatus,
    EmailTemplate,
    Note,
    Segment,
    Suppression,
    Task,
)
from src.models.event import Event
from src.models.idempotency import IdempotencyKey
from src.models.lead import Lead
from src.models.learning import Enrolment, LessonCompletion, LessonState
from src.models.learning_path import (
    LearningPath,
    LearningPathCourse,
    LearningPathTenantAssignment,
    PathEnrolment,
)
from src.models.media import TranscodeJob, VideoAsset, VideoHeartbeat, VideoProgress
from src.models.organisation import Organisation, OrganisationMember
from src.models.podcast import PodcastEpisode
from src.models.push import PushSubscription
from src.models.rbac import Permission, Role, RoleAssignment, RolePermission
from src.models.recommendation import Recommendation
from src.models.sso import TenantIdpConfig
from src.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionPlanCourse,
    SubscriptionStatus,
)
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
    SessionFacilitator,
    Workshop,
    WorkshopSession,
    WorkshopSessionStatus,
    WorkshopSessionType,
)

__all__ = [
    "AccessLevel",
    "Activity",
    "Article",
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
    "Campaign",
    "CampaignStatus",
    "Certificate",
    "CertificateTemplate",
    "ConsentRecord",
    "Contact",
    "Course",
    "CourseTenantAssignment",
    "CredentialStatus",
    "CredentialVerification",
    "CreditNote",
    "Deal",
    "DealStage",
    "EmailEvent",
    "EmailSend",
    "EmailSendStatus",
    "EmailTemplate",
    "Enrolment",
    "Entitlement",
    "Event",
    "Facilitator",
    "FacilitatorAvailability",
    "IdempotencyKey",
    "Invoice",
    "InvoiceItem",
    "InvoiceNumberCounter",
    "Lead",
    "LearningPath",
    "LearningPathCourse",
    "LearningPathTenantAssignment",
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
    "Note",
    "Order",
    "OrderItem",
    "Organisation",
    "OrganisationMember",
    "PasswordReset",
    "PathEnrolment",
    "Payment",
    "PaymentWebhook",
    "Permission",
    "PodcastEpisode",
    "Price",
    "Product",
    "PushSubscription",
    "QuestionBankItem",
    "Quiz",
    "QuizAnswer",
    "QuizAttempt",
    "QuizQuestion",
    "Recommendation",
    "RefreshToken",
    "Refund",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "Segment",
    "SessionFacilitator",
    "SoftDeleteMixin",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionPlanCourse",
    "SubscriptionStatus",
    "Suppression",
    "Survey",
    "SurveyQuestion",
    "SurveyResponse",
    "SurveyResponseMode",
    "Task",
    "TaxRule",
    "Tenant",
    "TenantDomain",
    "TenantIdpConfig",
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
