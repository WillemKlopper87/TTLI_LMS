"""Outbound email.

Local and CI point SMTP at Mailhog (no auth, no TLS) — messages are visible at
its web UI rather than actually delivered. Production points the same settings
at the external ESP named in the stack table; this module does not change
between the two, only the host/port do.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from src.core.config import Settings
from src.core.logging import get_logger

log = get_logger(__name__)


def _send_sync(settings: Settings, *, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


async def send_email(settings: Settings, *, to: str, subject: str, body: str) -> None:
    """Fire-and-forget from the caller's perspective: a mail outage must never
    fail the request that triggered it (e.g. a magic-link request, which
    returns 204 regardless of whether the address exists)."""
    try:
        await asyncio.to_thread(_send_sync, settings, to=to, subject=subject, body=body)
    except OSError:
        log.error("email_send_failed", to_domain=to.rsplit("@", 1)[-1])


__all__ = ["send_email"]
