"""Outbound email.

Sending happens on the arq worker (src/workers/main.py:send_email_job), not
in the request path: an SMTP handshake is slow and this call must never make
a request wait on it or fail because of it (e.g. a magic-link request, which
returns 204 regardless of whether the address exists). Enqueueing also gets
retries for free — arq retries a job that raises, with backoff — instead of
a transient SMTP outage silently losing the message.

Local and CI point SMTP at Mailhog (no auth, no TLS) — messages are visible
at its web UI rather than actually delivered. Production points the same
settings at the external ESP named in the stack table; this module does not
change between the two, only the host/port do.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from src.core.config import Settings
from src.core.logging import get_logger
from src.core.queue import get_queue

log = get_logger(__name__)

SEND_EMAIL_JOB = "send_email_job"


def send_sync(settings: Settings, *, to: str, subject: str, body: str) -> None:
    """Called by the worker job, not directly — exported for it to import.

    Raises on failure so arq's retry applies; the caller here is the worker,
    which is allowed to be slow and to fail loudly.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


async def send_email(settings: Settings, *, to: str, subject: str, body: str) -> None:
    """Enqueue delivery. Never raises — an enqueue failure (Redis down) must
    not fail the request that triggered it, same reasoning as the SMTP
    failure this used to swallow directly."""
    try:
        await get_queue().enqueue_job(SEND_EMAIL_JOB, to=to, subject=subject, body=body)
    except Exception:
        log.error("email_enqueue_failed", to_domain=to.rsplit("@", 1)[-1])


__all__ = ["SEND_EMAIL_JOB", "send_email", "send_sync"]
