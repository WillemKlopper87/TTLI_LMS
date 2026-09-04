"""Pure-function tests for the tenant->course->per-upload video-settings
chain (`services/media/video_settings.py`, migration 0040) — no Postgres,
no Redis. `resolve_default_rungs`/`resolve_allow_bypass`/`estimate_sizes`
are already pure over already-loaded ORM objects; before this file, they
had zero test coverage at all (TTLI_Audit_Report_2026-09-02.md's M2/M5 both
name this exact module as the gap).

`Course`/`Tenant` are constructed directly (SQLAlchemy's declarative
`__init__` accepts mapped-column keywords) rather than through a session —
these functions only ever read plain attributes, so no DB is needed.
"""

from __future__ import annotations

import pytest
from src.models.course import Course
from src.models.tenant import Tenant
from src.services.media.ffmpeg import DEFAULT_RUNGS, LADDER
from src.services.media.video_settings import (
    estimate_sizes,
    resolve_allow_bypass,
    resolve_default_rungs,
)

pytestmark = pytest.mark.unit


def _course(video_settings: dict[str, object] | None = None) -> Course:
    return Course(video_settings=video_settings or {})


def _tenant(settings: dict[str, object] | None = None) -> Tenant:
    return Tenant(settings=settings or {})


# ---------------------------------------------------------- estimate_sizes


def test_estimate_sizes_matches_ladder_bitrate_times_duration():
    sizes = estimate_sizes(5.0, has_audio=True)
    for rung, cfg in LADDER.items():
        kbps = cfg["video_kbps"] + cfg["audio_kbps"]
        assert sizes[rung] == round(kbps * 1000 / 8 * 5.0)


def test_estimate_sizes_without_audio_excludes_audio_kbps():
    with_audio = estimate_sizes(10.0, has_audio=True)
    without_audio = estimate_sizes(10.0, has_audio=False)
    for rung, cfg in LADDER.items():
        assert without_audio[rung] == round(cfg["video_kbps"] * 1000 / 8 * 10.0)
        assert with_audio[rung] > without_audio[rung]


def test_estimate_sizes_covers_every_known_rung():
    sizes = estimate_sizes(60.0, has_audio=True)
    assert set(sizes.keys()) == set(LADDER.keys())


def test_estimate_sizes_zero_duration_is_zero_bytes():
    sizes = estimate_sizes(0.0, has_audio=True)
    assert all(v == 0 for v in sizes.values())


# ---------------------------------------------------------- resolve_default_rungs


def test_resolve_default_rungs_falls_back_to_hardcoded_default():
    assert resolve_default_rungs(None, _tenant()) == list(DEFAULT_RUNGS)
    assert resolve_default_rungs(_course(), _tenant()) == list(DEFAULT_RUNGS)


def test_resolve_default_rungs_tenant_overrides_hardcoded_default():
    tenant = _tenant({"video": {"rungs": ["360p", "480p"]}})
    assert resolve_default_rungs(None, tenant) == ["360p", "480p"]
    assert resolve_default_rungs(_course(), tenant) == ["360p", "480p"]


def test_resolve_default_rungs_course_overrides_tenant():
    course = _course({"rungs": ["720p", "1080p"]})
    tenant = _tenant({"video": {"rungs": ["360p", "480p"]}})
    assert resolve_default_rungs(course, tenant) == ["720p", "1080p"]


def test_resolve_default_rungs_empty_course_list_falls_through_to_tenant():
    # An empty list is "not set", not "explicitly zero rungs" -- the chain
    # falls through to the next tier rather than resolving to nothing.
    course = _course({"rungs": []})
    tenant = _tenant({"video": {"rungs": ["360p"]}})
    assert resolve_default_rungs(course, tenant) == ["360p"]


def test_resolve_default_rungs_malformed_tenant_video_key_is_ignored():
    # tenant.settings["video"] is supposed to be a dict; a malformed value
    # (e.g. from hand-edited settings) must not crash the resolver.
    tenant = _tenant({"video": "not-a-dict"})
    assert resolve_default_rungs(None, tenant) == list(DEFAULT_RUNGS)


# ---------------------------------------------------------- resolve_allow_bypass


def test_resolve_allow_bypass_defaults_true():
    assert resolve_allow_bypass(None, _tenant()) is True
    assert resolve_allow_bypass(_course(), _tenant()) is True


def test_resolve_allow_bypass_tenant_can_disable():
    tenant = _tenant({"video": {"allow_bypass": False}})
    assert resolve_allow_bypass(None, tenant) is False


def test_resolve_allow_bypass_course_overrides_tenant():
    course = _course({"allow_bypass": True})
    tenant = _tenant({"video": {"allow_bypass": False}})
    assert resolve_allow_bypass(course, tenant) is True

    course_off = _course({"allow_bypass": False})
    tenant_on = _tenant({"video": {"allow_bypass": True}})
    assert resolve_allow_bypass(course_off, tenant_on) is False


def test_resolve_allow_bypass_course_false_is_distinct_from_unset():
    # False must be honoured, not treated the same as "no value" -- this
    # is exactly the bug shape a naive `if course_value:` check would
    # introduce (False is falsy, but it is a real, deliberate setting).
    course = _course({"allow_bypass": False})
    tenant = _tenant()
    assert resolve_allow_bypass(course, tenant) is False
