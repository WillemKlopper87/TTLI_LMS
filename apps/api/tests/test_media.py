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
        headers={"Authorization": f"Bearer {buyer_token}", "Idempotency-Key": uuid.uuid4().hex},
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
        headers={"Authorization": f"Bearer {finance_token}", "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200, approve.text
    return buyer_token, buyer_id


@pytest.fixture(autouse=True)
async def _cleanup_seeded_lesson_blocks(tenant_session_factory):  # type: ignore[no-untyped-def]
    """Same cleanup as test_assessment.py's fixture of the same name —
    see its docstring. Video attach now creates a block (0041) rather
    than overwriting the lesson's one FK, so the seeded lesson's video
    blocks would otherwise accumulate across every test in this file
    that attaches to it."""
    yield
    async with tenant_session_factory(None) as s:
        await s.execute(
            sa.text(
                "DELETE FROM lesson_blocks WHERE block_type != 'text' AND lesson_id IN ("
                "  SELECT l.id FROM lessons l "
                "  JOIN modules m ON m.id = l.module_id "
                "  JOIN courses c ON c.id = m.course_id "
                "  WHERE c.slug = 'executive-leadership-certificate'"
                ")"
            )
        )
        await s.commit()


async def _create_video_block(client, author_token: str, lesson_id: str) -> str:
    block = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"block_type": "video"},
    )
    assert block.status_code == 201, block.text
    return str(block.json()["id"])


async def _attach_video(client, author_token: str, lesson_id: str, video_asset_id: str) -> str:
    """0041: attaching now targets a block, not the lesson directly —
    create the block, then attach. Returns the new block's id. Only for
    setup call sites that expect the attach itself to succeed — tests of
    attach's own validation logic create the block via
    `_create_video_block` and call the attach endpoint directly, so they
    can assert on its actual (possibly non-204) response."""
    block_id = await _create_video_block(client, author_token, lesson_id)
    attach = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert attach.status_code == 204, attach.text
    return block_id


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


async def _create_course_lesson(client, author_token: str, *, title: str) -> tuple[str, str]:
    """A fresh course/module/lesson via the real authoring API, isolated
    from the shared seeded 'executive-leadership-certificate' course —
    the H1 regression tests below change a course's video-settings, which
    must not leak into other tests relying on the seeded course's own
    lesson positions."""
    course = await client.post(
        "/api/v1/courses",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": title},
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    module = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Module 1"},
    )
    assert module.status_code == 201, module.text
    module_id = module.json()["id"]
    lesson = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"title": "Lesson 1"},
    )
    assert lesson.status_code == 201, lesson.text
    return course_id, lesson.json()["id"]


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


async def _upload_draft(
    client, author_token: str, sample_video: Path, *, course_id: str | None = None
) -> str:  # type: ignore[no-untyped-def]
    """Phase 1 only (0040) — leaves the asset in state="draft", exercising
    the real course_id-resolution path the H1 regression tests need,
    unlike _upload_and_wait_ready which never touches finalize at all."""
    video_bytes = await asyncio.to_thread(sample_video.read_bytes)
    resp = await client.post(
        "/api/v1/video-assets",
        headers={"Authorization": f"Bearer {author_token}"},
        files={"file": ("lesson.mp4", video_bytes, "video/mp4")},
        data={"course_id": course_id} if course_id else {},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _finalize_transcode(client, author_token: str, video_asset_id: str) -> None:
    resp = await client.post(
        f"/api/v1/video-assets/{video_asset_id}/finalize",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"mode": "transcode", "rungs": ["480p"]},
    )
    assert resp.status_code == 200, resp.text

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


async def _finalize_as_is(client, author_token: str, video_asset_id: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/video-assets/{video_asset_id}/finalize",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"mode": "as_is"},
    )


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


async def test_list_video_assets_returns_uploaded_assets(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )

    listed = await client.get(
        "/api/v1/video-assets", headers={"Authorization": f"Bearer {author_token}"}
    )
    assert listed.status_code == 200, listed.text
    # VideoAsset is global, like Course/Quiz/Survey/Assignment — other
    # tests' assets are present too, so assert by membership, not equality.
    item = next(v for v in listed.json()["items"] if v["id"] == video_asset_id)
    assert item["state"] == "ready"
    assert item["duration_seconds"] == 3
    assert item["has_captions"] is False


async def test_video_asset_list_requires_course_edit_permission(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    # The real seeded learner role (course:view + lesson:complete), not
    # role=None — VideoAsset carries no answer-key-equivalent secret the
    # way a quiz's `correct` flags do, but an arbitrary learner still
    # shouldn't be able to browse the admin's video-asset inventory.
    learner_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="learner"
    )
    resp = await client.get(
        "/api/v1/video-assets", headers={"Authorization": f"Bearer {learner_token}"}
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
    await _attach_video(client, author_token, lesson_id, video_asset_id)

    # An account with no entitlement at all — no order, no enrolment.
    stranger_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role=None
    )
    resp = await client.get(
        f"/api/v1/media/{video_asset_id}/playback",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert resp.status_code == 403


async def test_guest_playback_of_a_public_lesson_is_watermarked_as_sample(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    """P13/REQ-LEAD-05: a guest's stream must read as sample content, not
    just be traced by identity like a paying learner's. A brand new lesson
    is used (not the shared seeded position=1 one every other test in this
    file attaches to) so this can't affect those tests' access checks."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )
    async with tenant_session_factory(tenant_id) as s:
        module_id = str(
            (
                await s.execute(
                    sa.text(
                        "SELECT m.id FROM modules m JOIN courses c ON c.id = m.course_id "
                        "WHERE c.slug = 'executive-leadership-certificate' LIMIT 1"
                    )
                )
            ).scalar_one()
        )
    lesson = await client.post(
        f"/api/v1/modules/{module_id}/lessons",
        json={"title": "Guest Sample Lesson", "access_level": "public"},
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert lesson.status_code == 201, lesson.text
    lesson_id = lesson.json()["id"]
    await _attach_video(client, author_token, lesson_id, video_asset_id)

    guest_email = _unique_email()
    async with tenant_session_factory(tenant_id) as s:
        await identity.create_user(
            s, crypto, tenant_id=tenant_id, email=guest_email, is_guest=True, guest_days=7
        )
        raw = await identity.create_magic_link(
            s, crypto, tenant_id=tenant_id, email=guest_email, minutes=15
        )
    consumed = await client.post("/api/v1/auth/magic-link/consume", json={"token": raw})
    assert consumed.status_code == 200, consumed.text
    guest_token = consumed.json()["access_token"]

    resp = await client.get(
        f"/api/v1/media/{video_asset_id}/playback",
        headers={"Authorization": f"Bearer {guest_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["watermark"]["text"].startswith("SAMPLE · GUEST ACCESS · ")


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
    await _attach_video(client, author_token, lesson_id, video_asset_id)

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
    await _attach_video(client, author_token, lesson_id, video_asset_id)

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
            asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        await playback.mint(
            redis,
            user_id=user_id,
            asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        third = await playback.mint(
            redis,
            user_id=user_id,
            asset_id=video_asset_id,
            expires_in=60,
            max_concurrent_sessions=2,
        )
        # REQ-BYPASS-09: the oldest (first) session is terminated, not the
        # newest — the person in front of the screen right now keeps
        # playing.
        assert await playback.validate(redis, token=first, asset_id=video_asset_id) is None
        assert await playback.validate(redis, token=third, asset_id=video_asset_id) == user_id
    finally:
        await redis.flushdb()
        await redis.aclose()


async def test_heartbeat_records_progress_and_rejects_a_seek_beyond_furthest(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    # No real video asset needed — heartbeat mechanics only require a
    # video block to exist and belong to this lesson (0041).
    block_id = await _create_video_block(client, author_token, lesson_id)
    token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )

    first = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "position_seconds": 1,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert first.status_code == 200
    assert Decimal(first.json()["furthest_position_seconds"]) == Decimal("1")

    seek = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "position_seconds": 500,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert seek.status_code == 400
    assert seek.json()["error"]["code"] == "SEEK_NOT_PERMITTED"


async def test_heartbeat_rejects_playback_rate_above_the_configured_maximum(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    block_id = await _create_video_block(client, author_token, lesson_id)
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
        json={
            "block_id": block_id,
            "position_seconds": 1,
            "playback_rate": 8.0,
            "session_id": "s1",
        },
    )
    assert resp.status_code == 400


async def test_heartbeat_reports_the_rule_the_player_is_being_measured_against(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    """The player draws a progress ring; it must not have to derive the
    numbers behind it. The heartbeat ack now carries the server's own
    watched percentage, the asset's duration, and whatever
    `video_watch_percentage` the merged completion rules require (null
    when no such rule applies) — read back *after* the write, so it is
    this heartbeat's result, not the previous one's."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    video_asset_id = await _upload_and_wait_ready(
        client, author_token, sample_video, tenant_session_factory
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    block_id = await _attach_video(client, author_token, lesson_id, video_asset_id)

    token, _ = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )

    resp = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "position_seconds": 1,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The original counters are untouched.
    assert Decimal(body["furthest_position_seconds"]) == Decimal("1")
    assert Decimal(body["watched_seconds"]) == Decimal("0")
    assert body["duration_seconds"] == 3  # the 3-second synthetic clip
    # The first heartbeat has no previous one to measure an interval
    # against (REQ-BYPASS-03), so nothing counts as watched yet — 0%, not
    # null, because a progress row now exists.
    assert body["watched_percentage"] == 0
    # 0011 seeds only minimum_time_seconds on this lesson, so there is no
    # watch-percentage rule to report.
    assert body["required_percentage"] is None


async def _enrolment_id_for(tenant_session_factory, tenant_id, user_id) -> str:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return str(
            (
                await s.execute(
                    sa.text("SELECT id FROM enrolments WHERE user_id = :u"), {"u": user_id}
                )
            ).scalar_one()
        )


async def _watched_seconds(tenant_session_factory, tenant_id, *, enrolment_id, block_id) -> Decimal:  # type: ignore[no-untyped-def]
    async with tenant_session_factory(tenant_id) as s:
        return (
            await s.execute(
                sa.text(
                    "SELECT watched_seconds FROM video_progress "
                    "WHERE enrolment_id = :e AND lesson_block_id = :b"
                ),
                {"e": enrolment_id, "b": block_id},
            )
        ).scalar_one()


async def _backdate_last_heartbeat(
    tenant_session_factory, tenant_id, *, enrolment_id, block_id, seconds_ago: int
) -> None:  # type: ignore[no-untyped-def]
    """Rather than sleeping the test past HEARTBEAT_MAX_INTERVAL_SECONDS,
    push the row's own `last_heartbeat_at` into the past — the same
    "change the clock's input, not the app's evaluation logic" reasoning
    test_learning.py's `_backdate_first_seen` already uses."""
    async with tenant_session_factory(tenant_id) as s:
        await s.execute(
            sa.text(
                "UPDATE video_progress SET last_heartbeat_at = now() - make_interval(secs => :s) "
                "WHERE enrolment_id = :e AND lesson_block_id = :b"
            ),
            {"s": seconds_ago, "e": enrolment_id, "b": block_id},
        )
        await s.commit()


async def test_parallel_heartbeats_do_not_multiply_watch_time(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-6: `record_heartbeat` used to read the progress row with no
    lock and cap only the wall-clock gap per call — N heartbeats landing
    concurrently each independently computed up to
    HEARTBEAT_MAX_INTERVAL_SECONDS of "elapsed" off the same stale
    `last_heartbeat_at`, so `watched_seconds` grew by N times the real
    gap instead of once. The row is now locked (`FOR UPDATE`) for the
    duration of the update, so concurrent callers serialise rather than
    all reading the same starting point."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    block_id = await _create_video_block(client, author_token, lesson_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )

    baseline = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "position_seconds": 0,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert baseline.status_code == 200, baseline.text

    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)
    # Simulate a genuine 3-second gap since that heartbeat, without
    # actually sleeping the test — kept inside SEEK_TOLERANCE_SECONDS of
    # the baseline position (2s) so the position each parallel caller
    # reports below still passes the (unrelated, pre-existing) seek
    # check; the point here is the concurrency race, not the seek limit.
    await _backdate_last_heartbeat(
        tenant_session_factory,
        tenant_id,
        enrolment_id=enrolment_id,
        block_id=block_id,
        seconds_ago=3,
    )

    async def _beat():  # type: ignore[no-untyped-def]
        return await client.post(
            f"/api/v1/lessons/{lesson_id}/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "block_id": block_id,
                # Every parallel caller reports the same position — five
                # browser tabs all mid-way through the same 3-second gap.
                "position_seconds": 2,
                "playback_rate": 1.0,
                "session_id": "s1",
            },
        )

    responses = await asyncio.gather(*[_beat() for _ in range(5)])
    for r in responses:
        assert r.status_code == 200, r.text

    watched = await _watched_seconds(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, block_id=block_id
    )
    # Pre-fix, each of the 5 concurrent calls would independently read
    # the same stale last_heartbeat_at and add ~3s, totalling ~15s. Now
    # the lock serialises them (every call after the first sees an
    # already-advanced last_heartbeat_at, so contributes ~0) and the
    # position-delta bound caps even the first — nowhere near 5 x 3s.
    assert watched <= Decimal("6"), watched


async def test_heartbeat_at_an_unchanged_position_does_not_accrue_watched_time(
    client, tenant_session_factory, crypto
) -> None:  # type: ignore[no-untyped-def]
    """H-6's other half: a heartbeat reporting the *same* position as
    last time — paused, or simply called again — used to still add up to
    HEARTBEAT_MAX_INTERVAL_SECONDS of watched time per call, bounded
    only by wall-clock elapsed. It is now also bounded by how far
    position has genuinely moved since the row's own last heartbeat."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    price_id = await _demo_price_id(tenant_session_factory, tenant_id)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    lesson_id = await _seeded_lesson_id(tenant_session_factory, tenant_id, position=1)
    block_id = await _create_video_block(client, author_token, lesson_id)
    token, buyer_id = await _enrol_via_eft(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, price_id=price_id
    )
    await client.post(
        f"/api/v1/lessons/{lesson_id}/start", headers={"Authorization": f"Bearer {token}"}
    )

    baseline = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            # Within SEEK_TOLERANCE_SECONDS (2) of a fresh row's
            # furthest_position_seconds=0.
            "position_seconds": 2,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert baseline.status_code == 200, baseline.text

    enrolment_id = await _enrolment_id_for(tenant_session_factory, tenant_id, buyer_id)
    await _backdate_last_heartbeat(
        tenant_session_factory,
        tenant_id,
        enrolment_id=enrolment_id,
        block_id=block_id,
        seconds_ago=30,
    )

    # 30 real seconds have "passed", but position hasn't moved — the
    # video is paused (or the client just called this again).
    repeat = await client.post(
        f"/api/v1/lessons/{lesson_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "block_id": block_id,
            "position_seconds": 2,
            "playback_rate": 1.0,
            "session_id": "s1",
        },
    )
    assert repeat.status_code == 200, repeat.text

    watched = await _watched_seconds(
        tenant_session_factory, tenant_id, enrolment_id=enrolment_id, block_id=block_id
    )
    # Only the seek-tolerance slack, never anywhere near the full 30s gap.
    assert watched <= Decimal("2"), watched


# ============================================================ H1 regression
# The 2026-09-02 audit found that `attach_video_to_lesson` never resolved
# the lesson's actual course, never required the asset to be ready, and
# never re-checked progressive-delivery policy against where the video
# was actually landing — `course_id` and `allow_bypass` were real at
# upload/finalize time but purely advisory by the time a video reached a
# lesson. These four tests pin the fix in routers/media.py directly.


async def test_attach_rejects_a_video_that_is_not_ready(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    _, lesson_id = await _create_course_lesson(client, author_token, title="H1 not-ready course")
    video_asset_id = await _upload_draft(client, author_token, sample_video)
    block_id = await _create_video_block(client, author_token, lesson_id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 400, resp.text


async def test_attach_binds_an_unbound_asset_to_its_destination_course(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course_id, lesson_id = await _create_course_lesson(client, author_token, title="H1 bind course")
    # No course_id hint at upload — attach is the first place this asset's
    # course is ever established.
    video_asset_id = await _upload_draft(client, author_token, sample_video)
    await _finalize_transcode(client, author_token, video_asset_id)
    block_id = await _create_video_block(client, author_token, lesson_id)

    resp = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 204, resp.text

    async with tenant_session_factory(None) as s:
        bound_course_id = (
            await s.execute(
                sa.text("SELECT course_id FROM video_assets WHERE id = :id"),
                {"id": video_asset_id},
            )
        ).scalar_one()
    assert str(bound_course_id) == course_id


async def test_attach_rejects_reusing_an_asset_bound_to_a_different_course(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course_a, lesson_a = await _create_course_lesson(client, author_token, title="H1 course A")
    _course_b, lesson_b = await _create_course_lesson(client, author_token, title="H1 course B")

    video_asset_id = await _upload_draft(client, author_token, sample_video, course_id=course_a)
    await _finalize_transcode(client, author_token, video_asset_id)

    block_a = await _create_video_block(client, author_token, lesson_a)
    first_attach = await client.post(
        f"/api/v1/lessons/{lesson_a}/blocks/{block_a}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert first_attach.status_code == 204, first_attach.text

    block_b = await _create_video_block(client, author_token, lesson_b)
    cross_course_attach = await client.post(
        f"/api/v1/lessons/{lesson_b}/blocks/{block_b}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert cross_course_attach.status_code == 400, cross_course_attach.text


async def test_attach_rejects_progressive_video_after_the_destination_courses_policy_tightens(
    client, tenant_session_factory, crypto, sample_video
) -> None:  # type: ignore[no-untyped-def]
    """The exact H1 scenario: bypass was allowed when the asset was
    finalised, then the destination course's own policy tightened before
    the video was ever attached anywhere."""
    tenant_id = await _demo_tenant_id(tenant_session_factory)
    author_token, _ = await _login(
        client, tenant_session_factory, crypto, tenant_id=tenant_id, role="content_author"
    )
    course_id, lesson_id = await _create_course_lesson(
        client, author_token, title="H1 policy-tightens course"
    )

    video_asset_id = await _upload_draft(client, author_token, sample_video, course_id=course_id)
    as_is = await _finalize_as_is(client, author_token, video_asset_id)
    assert as_is.status_code == 200, as_is.text
    assert as_is.json()["delivery_mode"] == "progressive"

    tighten = await client.patch(
        f"/api/v1/courses/{course_id}/video-settings",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"allow_bypass": False},
    )
    assert tighten.status_code == 200, tighten.text

    block_id = await _create_video_block(client, author_token, lesson_id)
    resp = await client.post(
        f"/api/v1/lessons/{lesson_id}/blocks/{block_id}/video?video_asset_id={video_asset_id}",
        headers={"Authorization": f"Bearer {author_token}"},
    )
    assert resp.status_code == 400, resp.text
