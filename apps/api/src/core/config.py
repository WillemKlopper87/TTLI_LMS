"""Application configuration.

`DATABASE_URL` deliberately has no default. An application that guesses its own
database will eventually guess a production one.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Core ---
    environment: Environment = "local"
    debug: bool = False
    api_port: int = 8010
    secret_key: str = ""
    # The web app's own origin — needed wherever an absolute, scannable
    # URL must be embedded outside a browser context (certificate QR
    # codes, REQ-CRED-02) rather than a relative one the BFF would resolve.
    public_web_url: str = "http://localhost:3010"
    # The API's own public origin — needed for exactly one thing: the
    # `notify_url` a payment gateway's webhook calls. Every *browser*
    # request reaches the API only through apps/web's BFF (no CORS
    # surface, by design), but a gateway webhook is a server calling a
    # server, not a browser — same-origin policy doesn't apply, and
    # routing it through the BFF would mean giving Next.js an
    # unauthenticated pass-through route for no benefit. In production
    # this points at whatever hostname the edge (Front Door/App Gateway)
    # routes to the API's own container, alongside the BFF's — an infra
    # routing decision, not one this setting makes.
    api_public_url: str = "http://localhost:8010"

    # --- Database ---
    database_url: str
    database_url_sync: str = ""
    # Password for the non-superuser role the app connects as (DATABASE_URL).
    # Migrations create the role and grant it; they still run as the superuser
    # named in DATABASE_URL_SYNC, since DDL and role creation need that.
    app_db_password: str = ""

    # --- Redis ---
    redis_url: str = "redis://localhost:6399/0"

    # --- Networking ---
    # Honour X-Forwarded-For for per-IP rate limiting and audit rows.
    # Enable ONLY when the API is reachable exclusively through the BFF
    # (or another trusted proxy) — with the API directly reachable, any
    # caller could spoof the header and dodge every per-IP limit. See
    # src/core/net.py for the full reasoning.
    trust_x_forwarded_for: bool = False

    # --- Auth ---
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    magic_link_minutes: int = 15
    password_reset_minutes: int = 30
    mfa_pending_minutes: int = 5
    mfa_enroll_minutes: int = 10
    mfa_issuer_name: str = "TTLI"
    # 01 §1.4 decision #6 (7 vs 14 days) is unsigned — configurable via env
    # rather than hardcoded, same placeholder pattern as tenant_themes' seed
    # colors. 7 is the conservative default until the customer signs off.
    guest_access_days: int = 7

    # --- Commerce (02 §6) ---
    # Real values are finance's, not engineering's, to invent — placeholders
    # so POST /orders/{id}/checkout/eft has something to display rather than
    # nothing, same reasoning as guest_access_days above.
    eft_bank_name: str = "Not yet configured"
    eft_account_name: str = "Not yet configured"
    eft_account_number: str = "Not yet configured"
    eft_branch_code: str = "Not yet configured"
    supplier_vat_number: str = ""
    # REQ-PAY-12: subscriptions behind a feature flag pending 01 §1.4 #5 —
    # that decision is now made (multi-tier, EFT/PO-funded renewals, see
    # 0021's migration docstring), so this defaults on; the flag stays so a
    # deployment can still turn it off without a redeploy.
    subscriptions_enabled: bool = True

    # --- Card checkout: Payfast (03 §5.2/5.7) ---
    # No live sandbox account exists (01 §1.4's Phase 0 outstanding list) —
    # every empty default below means card checkout is correctly *disabled*
    # (services/payments/payfast.py refuses to initiate a checkout with no
    # merchant_id configured) rather than silently attempting one with
    # invented credentials. Set these three from a real Payfast account to
    # turn card checkout on; nothing else in the code needs to change.
    payfast_merchant_id: str = ""
    payfast_merchant_key: str = ""
    payfast_passphrase: str = ""
    # Payfast's own recommended anti-forgery step beyond signature
    # checking: POST the received ITN straight back and require "VALID".
    # Sandbox and production use different hosts entirely, not a query
    # param — switching env changes the host, same as most gateways.
    payfast_sandbox: bool = True

    # --- Podcast Spotify metadata lookup (REQ-STORE-04) ---
    # Same empty-default, graceful-degradation shape as Payfast above:
    # services/spotify.py refuses to look anything up with no client_id
    # configured, and the admin curation UI falls back to manual entry —
    # this is a UX convenience (autofill title/duration/artwork from a
    # pasted episode URL), never a hard dependency for podcasts to work.
    # Client-credentials only (no user OAuth, no scopes needed) — register
    # a free Spotify Developer app to turn this on.
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    # --- Web Push (01 §5.9) ---
    # Unlike Payfast/Spotify above, VAPID is a self-generated keypair, not
    # a third party's credential — nothing external blocks this feature,
    # only whether a pair has been generated yet (services/push.py's
    # module docstring has the one-liner). Empty means push sends are
    # skipped, the same graceful-degradation shape as everything above.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # A contact URI VAPID requires the sender to identify itself with —
    # mailto: or an https: URL, so a push service that flags abuse has
    # somewhere to reach the sender.
    vapid_subject: str = "mailto:support@example.com"

    break_glass_admin_enabled: bool = False
    break_glass_admin_email: str = "admin@ttli.local"
    break_glass_admin_password: str = ""

    # --- Field encryption ---
    field_encryption_key: str = ""
    blind_index_key: str = ""

    # --- Object storage ---
    storage_backend: Literal["local", "s3", "azure"] = "local"
    storage_local_root: str = "var/storage"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "af-south-1"
    azure_storage_connection_string: str = ""

    # --- Virus scanning (04 §3, REQ-BYPASS-08) ---
    clamav_host: str = "localhost"
    clamav_port: int = 3410

    # --- Media pipeline (06 §3, 02 §5.4/5.5) ---
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    # arq's own default is 300s, which silently cancels any transcode
    # longer than five minutes — i.e. most real lecture video (fable5.1
    # review H-5). Six hours is a ceiling for a stuck job, not a target:
    # a genuine transcode that reaches it is wrong in some other way, and
    # the cancellation now leaves a failed row saying so rather than an
    # asset stuck on "transcoding".
    transcode_job_timeout_seconds: int = 21_600
    # 0040's as-is bypass: StorageService.get_object has no byte-range
    # support in any adapter, so a progressive file is served as one
    # full-body response, transiting API-process memory per request.
    # Bounded here rather than adding real Range/206 support (a bigger,
    # all-three-adapters change, left as a follow-up) — above this size
    # the admin UI simply doesn't offer the as-is toggle.
    bypass_max_size_bytes: int = 500_000_000
    # 03 §6.7's signed playback URL — short-lived, bound to user and
    # session, re-minted per playback attempt rather than cached.
    playback_url_expiry_seconds: int = 300
    # REQ-BYPASS-09 — deters account sharing without being aggressive
    # enough to frustrate a paying executive on two devices.
    max_concurrent_video_sessions: int = 2
    # REQ-BYPASS-03's tolerance for how far a heartbeat's position may
    # exceed wall-clock-bounded expectations before being rejected.
    heartbeat_max_playback_rate: float = 2.0

    # --- Email ---
    smtp_host: str = "localhost"
    smtp_port: int = 1145
    email_from: str = "no-reply@ttli.local"

    # --- Workshops (02 §9, REQ-WS-05/06) ---
    # Real values need an Azure AD app registration nobody has done yet —
    # blocked on external credentials, same class of gap as Phase 3's
    # Payfast/Netcash sandbox accounts (01 §1.4). `services/meeting/teams.py`
    # checks these and refuses cleanly rather than pretending to work.
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_tenant_id: str = ""
    # P7 phase 5: the single service mailbox every Teams meeting is
    # created on (as a calendar event, not the bare onlineMeetings
    # resource — that has no update/cancel primitive and sends no
    # invite). Facilitators and registrants are event *attendees*, not
    # the technical organiser, so no per-facilitator M365 licence or
    # delegated Graph permission is needed.
    graph_organiser_upn: str = ""

    # P13 phase 4: Zoom Server-to-Server OAuth app credentials — same
    # blocked-on-external-credentials gap as graph_*/Payfast/Netcash.
    # `services/meeting/zoom.py` checks these and refuses cleanly.
    zoom_account_id: str = ""
    zoom_client_id: str = ""
    zoom_client_secret: str = ""
    # The single Zoom user every meeting is created under — same one-
    # service-identity design as graph_organiser_upn, for the same
    # reason: no per-facilitator Zoom Pro licence is needed this way.
    # Facilitators are listed as alternative_hosts, learners as
    # registrants — Zoom has no single "attendees" list like Graph.
    zoom_organiser_email: str = ""

    # P13 phase 5: Google Meet via a Workspace service account with
    # domain-wide delegation — same blocked-on-external-credentials gap.
    # `services/meeting/meet.py` checks these and refuses cleanly.
    # `google_service_account_private_key` is the PEM string from the
    # service account's JSON key file's `private_key` field, used to
    # sign a JWT-bearer assertion (PyJWT + cryptography, already a
    # dependency — no new library for this).
    google_service_account_email: str = ""
    google_service_account_private_key: str = ""
    # The Workspace user impersonated (the JWT's `sub` claim) — same
    # one-service-identity design as graph_organiser_upn/
    # zoom_organiser_email, for the same reason: no per-facilitator
    # Workspace account or delegated Calendar scope is needed.
    google_organiser_email: str = ""

    # --- Observability ---
    sentry_dsn: str = ""
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return v

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations synchronously."""
        if self.database_url_sync:
            return self.database_url_sync
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def encryption_key_bytes(self) -> bytes:
        return base64.b64decode(self.field_encryption_key)

    def blind_index_key_bytes(self) -> bytes:
        return base64.b64decode(self.blind_index_key)


def check_production_safety(settings: Settings) -> list[str]:
    """Return every reason this configuration must not run in production.

    A list rather than a boolean, so the startup log names all the problems at
    once instead of revealing them one redeploy at a time.
    """
    problems: list[str] = []

    if not settings.is_production:
        return problems

    if settings.debug:
        problems.append("DEBUG is enabled")
    if settings.break_glass_admin_enabled:
        problems.append("BREAK_GLASS_ADMIN_ENABLED is on")
    if len(settings.secret_key) < 32:
        problems.append("SECRET_KEY is missing or shorter than 32 characters")
    if not settings.field_encryption_key:
        problems.append("FIELD_ENCRYPTION_KEY is not set")
    if not settings.blind_index_key:
        problems.append("BLIND_INDEX_KEY is not set")
    if not settings.app_db_password:
        problems.append("APP_DB_PASSWORD is not set")
    if settings.app_db_password in {"app_user_local_dev", "app_user_ci"}:
        problems.append("APP_DB_PASSWORD is a development credential")
    if settings.field_encryption_key == settings.blind_index_key:
        problems.append("FIELD_ENCRYPTION_KEY and BLIND_INDEX_KEY are the same value")
    if settings.storage_backend == "local":
        problems.append("STORAGE_BACKEND is 'local'")
    if settings.s3_access_key in {"ttli_dev", "minioadmin"}:
        problems.append("S3_ACCESS_KEY is a development credential")
    if not settings.sentry_dsn:
        problems.append("SENTRY_DSN is not set")
    if "localhost" in settings.database_url or "127.0.0.1" in settings.database_url:
        problems.append("DATABASE_URL points at localhost")
    if "sslmode=disable" in settings.database_url:
        problems.append("DATABASE_URL disables TLS")
    if "localhost" in settings.redis_url or "127.0.0.1" in settings.redis_url:
        # Tenant resolution and login rate limiting both depend on Redis now
        # (core/tenancy.py, services/rate_limit.py) — not just a cache.
        problems.append("REDIS_URL points at localhost")

    return problems


@lru_cache
def get_settings() -> Settings:
    # Values come from the environment and .env, so the required fields are not
    # passed positionally here.
    return Settings()


__all__ = ["Environment", "Field", "Settings", "check_production_safety", "get_settings"]
