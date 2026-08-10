"""Phase 4 sprint 2: the media pipeline (02 §5.4/5.5/7.3/7.4, 03 §6.3/6.7,
06 §3, REQ-BYPASS-02/03/04/09). Runs a *real* transcode against the local
ffmpeg install — the same "don't mock the thing a wire-protocol bug would
hide behind" reasoning test_antivirus.py already established for ClamAV;
a mocked ffmpeg would never have caught the two real bugs this sprint's
live smoke test found (a missing UPDATE grant on `lessons`, and this
Redis client returning `str` rather than `bytes`).
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from src.core.db import dispose_engine, init_engine
from src.core.queue import dispose_queue, init_queue
from src.core.redis import dispose_redis, init_redis
from src.main import create_app
from src.models.rbac import RoleAssignment
from src.services import identity
from src.services.media import ffmpeg as ffmpeg_service
from src.services.media import playback
from src.services.media.pipeline import transcode_video_asset
from src.services.storage import Container, get_storage_adapter

pytestmark = pytest.mark.integration

TENANT_HOST = "localhost"
PASSWORD = "correct horse battery staple 9!"


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((parsed.hostname or "localhost", parsed.port or 6379))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
async def client(settings, database_url):  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip(
            "no Redis on the configured REDIS_URL — run: "
            "docker compose -f infra/docker-compose.yml up -d redis"
        )
    init_engine(settings)
    redis = init_redis(settings)
    await redis.flushdb()
    await init_queue(settings)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.headers["X-Tenant-Host"] = TENANT_HOST
        yield c
    await dispose_engine()
    await dispose_redis()
    await dispose_queue()


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    if not _ffmpeg_available():
        pytest.skip("no ffmpeg/ffprobe on PATH")
    out_dir = tmp_path_factory.mktemp("media")
    source = out_dir / "source.mp4"

    async def _generate() -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-t",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(source),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    asyncio.run(_generate())
    assert source.exists()
    return source


def _unique_email() -> str:
    return f"media-{uuid.uuid4().hex[:12]}@example.com"


async def _demo_tenant_id(tenant_session_factory) -> uuid.UUID:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(None) as s:
        row = (await s.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _demo_price_id(tenant_session_factory, tenant_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        price_id = (await s.execute(sa.text("SELECT id FROM prices LIMIT 1"))).scalar_one()
    return str(price_id)


async def _login(
    client, tenant_session_factory, crypto, *, tenant_id, role: str | None
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        user = await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=email, password=PASSWORD
        )
        user_id = user.id
        if role is not None:
            s.add(RoleAssignment(tenant_id=tenant_id, user_id=user_id, role_code=role))

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return str(resp.json()["access_token"]), user_id


async def _enrol_via_eft(
    client, tenant_session_factory, crypto, *, tenant_id, price_id
) -> tuple[str, uuid.UUID]:  # type: ignore[no-untyped-def]
    buyer_token, buyer_id = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    finance_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="finance"
    )
    order = await client.post(
        "/api/v1/orders",
        json={
            "currency": "ZAR",
            "customer_type": "individual",
            "lines": [{"price_id": price_id, "quantity": 1}],
        },
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    order_id = order.json()["id"]
    checkout = await client.post(
        f"/api/v1/orders/{order_id}/checkout/eft",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    payment_id = checkout.json()["payment_id"]
    await client.post(
        f"/api/v1/orders/{order_id}/payment-proof",
        headers={"Authorization": f"Bearer {buyer_token}"},
        files={"file": ("proof.pdf", b"%PDF-fake-proof-of-payment", "application/pdf")},
    )
    approve = await client.post(
        f"/api/v1/payments/{payment_id}/approve",
        headers={"Authorization": f"Bearer {finance_token}"},
    )
    assert approve.status_code == 200, approve.text
    return buyer_token, buyer_id


async def _seeded_lesson_id(tenant_session_factory, tenant_id, *, position: int) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text(
                        "SELECT l.id FROM lessons l "
                        "JOIN modules m ON m.id = l.module_id "
                        "JOIN courses c ON c.id = m.course_id "
                        "WHERE c.slug = 'executive-leadership-certificate' AND l.position = :p"
                    ),
                    {"p": position},
                )
            ).scalar_one()
        )


async def _upload_and_wait_ready(
    client, author_token: str, sample_video: Path, tenant_session_factory
) -> str:  # type: ignore[no-untyped-def]
    """Uploads through the real endpoint, then runs the transcode pipeline
    inline (rather than requiring a live arq worker in the test process) —
    the same real ffmpeg invocation the worker would make, just awaited
    directly so the test doesn't need to poll."""
    video_bytes = await asyncio.to_thread(sample_video.read_bytes)
    resp = await client.post(
        "/api/v1/video-assets",
        headers={"Authorization": f"Bearer {author_token}"},
        files={"file": ("lesson.mp4", video_bytes, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    video_asset_id = resp.json()["id"]

    from src.core.config import Settings
    from src.core.db import get_sessionmaker

    settings = Settings()
    factory = get_sessionmaker()
    storage = get_storage_adapter(settings)
    async with factory() as session:
        await transcode_video_asset(
            session, storage, settings, video_asset_id=uuid.UUID(video_asset_id)
        )

    check = await client.get(
        f"/api/v1/video-assets/{video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert check.json()["state"] == "ready", check.json()
    return video_asset_id


async def test_real_transcode_produces_a_playable_ladder(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )

    async with tenant_session_factory(None) as s:
        row = (
            await s.execute(
                sa.text(
                    "SELECT duration_seconds, playlist_object_key, renditions "
                    "FROM video_assets WHERE id = :i"
                ),
                {"i": video_asset_id},
            )
        ).first()
    assert row is not None
    assert row[0] == 3  # the 3-second synthetic clip
    assert row[1] == f"video-assets/{video_asset_id}/master.m3u8"
    assert len(row[2]) == len(ffmpeg_service.DEFAULT_RUNGS)

    settings_module = __import__("src.core.config", fromlist=["Settings"])
    storage = get_storage_adapter(settings_module.Settings())
    master = await storage.get_object(
        Container.PRIVATE_CONTENT, f"video-assets/{video_asset_id}/master.m3u8"
    )
    assert b"#EXTM3U" in master
    assert b"#EXT-X-STREAM-INF" in master


async def test_video_upload_requires_course_edit_permission(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.post(
        "/api/v1/video-assets",
        headers={"Authorization": f"Bearer {learner_token}"},
        files={"file": ("lesson.mp4", sample_video.read_bytes(), "video/mp4")},
    )
    assert resp.status_code == 403


async def test_playback_requires_a_real_enrolment(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    attach = await client.post(
        f"/api/v1/lessons/{lesson_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach.status_code == 204

    # An account with no entitlement at all — no order, no enrolment.
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.get(
        f"/api/v1/media/{video_asset_id}/playback",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 403


async def test_enrolled_learner_can_play_and_the_manifest_carries_the_token(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    playback_resp = await client.get(
        f"/api/v1/media/{video_asset_id}/playback",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    assert playback_resp.status_code == 200
    body = playback_resp.json()
    assert body["watermark"]["text"]
    token = body["playlist_url"].rsplit("access_token=", 1)[-1]

    manifest_resp = await client.get(
        f"/api/v1/media/{video_asset_id}/hls/master.m3u8?access_token={token}"
    )
    assert manifest_resp.status_code == 200
    # Every real reference line carries the token — REQ-BYPASS/06 §3.2's
    # "segment requests accept ?access_token=" requirement, checked on the
    # actual served bytes, not just the playback-mint response.
    for line in manifest_resp.text.splitlines():
        if line and not line.startswith("#"):
            assert f"access_token={token}" in line


async def test_captions_upload_gated_and_served_through_signed_playback_token(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    """REQ-LMS-07: a WebVTT caption track, uploaded once by a content
    author, served through the exact same signed playback token as HLS
    segments — no separate entitlement path to get wrong (0015's
    migration docstring)."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    await client.post(
        f"/api/v1/lessons/{lesson_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )

    before = await client.get(
        f"/api/v1/video-assets/{video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert before.json()["has_captions"] is False

    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    forbidden = await client.post(
        f"/api/v1/video-assets/{video_asset_id}/captions",
        headers={"Authorization": f"Bearer {learner_token}"},
        files={
            "file": ("captions.vtt", b"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nHello.", "text/vtt")
        },
    )
    assert forbidden.status_code == 403

    invalid = await client.post(
        f"/api/v1/video-assets/{video_asset_id}/captions",
        headers={"Authorization": f"Bearer {author_token}"},
        files={"file": ("captions.vtt", b"not a real vtt file", "text/vtt")},
    )
    assert invalid.status_code == 400

    upload = await client.post(
        f"/api/v1/video-assets/{video_asset_id}/captions",
        headers={"Authorization": f"Bearer {author_token}"},
        files={
            "file": ("captions.vtt", b"WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nHello.", "text/vtt")
        },
    )
    assert upload.status_code == 204

    after = await client.get(
        f"/api/v1/video-assets/{video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert after.json()["has_captions"] is True

    buyer_token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    playback_resp = await client.get(
        f"/api/v1/media/{video_asset_id}/playback",
        headers={"Authorization": f"Bearer {buyer_token}"},
    )
    assert playback_resp.status_code == 200
    captions_url = playback_resp.json()["captions_url"]
    assert captions_url is not None
    assert captions_url.startswith(f"media/{video_asset_id}/hls/captions.vtt?access_token=")

    vtt_resp = await client.get(f"/api/v1/{captions_url}")
    assert vtt_resp.status_code == 200
    assert vtt_resp.headers["content-type"].startswith("text/vtt")
    assert vtt_resp.text.startswith("WEBVTT")


async def test_hls_route_rejects_an_invalid_token(client) -> None:  # type: ignore[no-untyped-def]
    resp = await client.get(
        f"/api/v1/media/{uuid.uuid4()}/hls/master.m3u8?access_token=not-a-real-token"
    )
    assert resp.status_code == 403


def test_rewrite_manifest_handles_ext_x_map_and_plain_lines() -> None:
    content = '#EXTM3U\n#EXT-X-MAP:URI="init_0.mp4"\n#EXTINF:6.0,\nseg_0_00000.m4s\n'
    rewritten = playback.rewrite_manifest(content, token="tok123")
    assert '#EXT-X-MAP:URI="init_0.mp4?access_token=tok123"' in rewritten
    assert "seg_0_00000.m4s?access_token=tok123" in rewritten
    assert "#EXTM3U" in rewritten  # untouched


async def test_concurrent_session_cap_evicts_the_oldest(settings) -> None:  # type: ignore[no-untyped-def]
    if not _redis_reachable(settings.redis_url):
        pytest.skip("no Redis on the configured REDIS_URL")
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    user_id = uuid.uuid4()
    video_asset_id = uuid.uuid4()
    try:
        first = await playback.mint(
            redis,
            user_id=user_id,
            video_asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        await playback.mint(
            redis,
            user_id=user_id,
            video_asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        third = await playback.mint(
            redis,
            user_id=user_id,
            video_asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        # REQ-BYPASS-09: the oldest (first) session is terminated, not the
        # newest — the person in front of the screen right now keeps
        # playing.
        assert await playback.validate(redis, token=first, video_asset_id=video_asset_id) is None
        assert await playback.validate(redis, token=third, video_asset_id=video_asset_id) == user_id
    finally:
        await redis.flushdb()
        await redis.aclose()


async def test_heartbeat_records_progress_and_rejects_a_seek_beyond_furthest(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )

    first = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"position_seconds": 1, "playback_rate": 1.0, "session_id": "s1"},
    )
    assert first.status_code == 200
    assert Decimal(first.json()["furthest_position_seconds"]) == Decimal("1")

    seek = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"position_seconds": 500, "playback_rate": 1.0, "session_id": "s1"},
    )
    assert seek.status_code == 400
    assert seek.json()["error"]["code"] == "SEEK_NOT_PERMITTED"


async def test_heartbeat_rejects_playback_rate_above_the_configured_maximum(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )
    resp = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        # settings.heartbeat_max_playback_rate defaults to 2.0.
        json={"position_seconds": 1, "playback_rate": 8.0, "session_id": "s1"},
    )
    assert resp.status_code == 400
