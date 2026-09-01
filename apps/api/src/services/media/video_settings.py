"""The tenant -> course -> per-upload video-settings chain (0040): which
rungs a new upload's decision panel pre-checks, and whether the as-is
bypass is offered at all. Pure functions over already-loaded ORM objects,
no session I/O — the same division of labour services/feature_flags.py
uses (routers do the fetching, this module does the resolving).

Per-upload override is not this module's concern: it's whatever the admin
actually submits to POST /video-assets/{id}/finalize, handled entirely in
routers/media.py. This module only resolves the two tiers *beneath* that
explicit choice.
"""

from __future__ import annotations

from src.models.course import Course
from src.models.tenant import Tenant
from src.services.media.ffmpeg import DEFAULT_RUNGS, LADDER

# LADDER's keys, ordered slowest connection first — the order the admin
# decision panel and settings checkboxes render in.
KNOWN_RUNGS: tuple[str, ...] = ("360p", "480p", "720p", "1080p")


def estimate_sizes(duration_seconds: float, *, has_audio: bool) -> dict[str, int]:
    """Bytes per rung: (video_kbps [+ audio_kbps]) * 1000 / 8 * duration.
    Deterministic from the ffprobe duration alone since every rung's
    maxrate/bufsize already caps real output near this figure — no
    encode needed for a first-order estimate."""
    sizes: dict[str, int] = {}
    for rung in KNOWN_RUNGS:
        cfg = LADDER[rung]
        kbps = int(cfg["video_kbps"]) + (int(cfg["audio_kbps"]) if has_audio else 0)
        sizes[rung] = round(kbps * 1000 / 8 * duration_seconds)
    return sizes


def _as_str_list(value: object) -> list[str] | None:
    if isinstance(value, list) and value:
        return [str(v) for v in value]
    return None


def resolve_default_rungs(course: Course | None, tenant: Tenant) -> list[str]:
    """course.video_settings["rungs"] (if non-empty) -> tenant.settings
    ["video"]["rungs"] (if non-empty) -> the hardcoded DEFAULT_RUNGS."""
    if course is not None:
        course_rungs = _as_str_list(course.video_settings.get("rungs"))
        if course_rungs is not None:
            return course_rungs
    tenant_video = tenant.settings.get("video", {})
    raw_rungs = tenant_video.get("rungs") if isinstance(tenant_video, dict) else None
    tenant_rungs = _as_str_list(raw_rungs)
    if tenant_rungs is not None:
        return tenant_rungs
    return list(DEFAULT_RUNGS)


def resolve_allow_bypass(course: Course | None, tenant: Tenant) -> bool:
    """course.video_settings["allow_bypass"] (if set) -> tenant.settings
    ["video"]["allow_bypass"] (if set) -> True (bypass allowed by
    default — this only ever gates an already-authenticated, already-
    course:edit-authorised content author's own upload, so widening
    their choice at upload time introduces no new risk)."""
    if course is not None:
        course_value = course.video_settings.get("allow_bypass")
        if course_value is not None:
            return bool(course_value)
    tenant_value = tenant.settings.get("video", {}).get("allow_bypass")
    if tenant_value is not None:
        return bool(tenant_value)
    return True


__all__ = [
    "KNOWN_RUNGS",
    "estimate_sizes",
    "resolve_allow_bypass",
    "resolve_default_rungs",
]
