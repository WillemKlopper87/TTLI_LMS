"""What happens to a transcode that is cancelled part-way (fable5.1
review H-5).

arq's default `job_timeout` is 300 seconds and nothing overrode it, so
any transcode longer than five minutes — which is most real lecture
video — was cancelled mid-flight. Nothing handled that cancellation:
`video_assets.state` had been committed as `transcoding` before ffmpeg
started and nothing ever wrote it again, so the asset sat in that state
for ever while the operations screen, which lists only *failed* jobs,
showed nothing at all. The ffmpeg child was never killed either; it went
on transcoding an asset nobody was waiting for.

The timeout itself is asserted in `tests/test_config.py`. What is here is
the behaviour that has to hold when a cancellation does arrive, from
whatever source — the job timeout, a worker shutdown, a redeploy.

**On the patching.** These two tests replace ffmpeg, not the code under
test. `run_transcode`'s own ffmpeg invocation is covered for real by
`test_media.py::test_real_transcode_produces_a_playable_ladder`; a
cancellation, by definition, has to be delivered while a child process is
still running, and waiting out a real transcode to do that would make the
test both slow and timing-dependent. So the subprocess is a real child
process that sleeps, and the pipeline's own bookkeeping — the state
transitions, the shielded commit — is genuinely executed against a real
database.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from src.core.config import Settings
from src.core.db import dispose_engine, init_engine
from src.core.ids import uuid7
from src.models.media import VideoAsset
from src.services.media import ffmpeg as ffmpeg_service
from src.services.media import pipeline as pipeline_module
from src.services.media.ffmpeg import ProbeResult
from src.services.media.transcoder import run_transcode
from src.services.storage import Container, get_storage_adapter

pytestmark = pytest.mark.integration


def _database_reachable(url: str) -> bool:
    parsed = urlparse(url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((parsed.hostname or "localhost", parsed.port or 5432))
        return True
    except OSError:
        return False
    finally:
        sock.close()


async def test_a_cancelled_transcode_kills_its_ffmpeg_child(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """ffmpeg is a separate OS process: cancelling the coroutine that
    spawned it does nothing to it on its own. It would keep burning a CPU
    on an asset nobody wants, writing into a temporary directory the
    caller is about to delete."""
    spawned: list[asyncio.subprocess.Process] = []
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        # A real child, just one that outlives the test's patience rather
        # than one that needs ffmpeg installed.
        proc = await real_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        spawned.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    task = asyncio.create_task(
        run_transcode(
            tmp_path / "source.mp4",
            tmp_path / "out",
            ("480p",),
            ProbeResult(duration_seconds=600.0, has_audio=True, fps=25.0),
            ffmpeg_path="ffmpeg",
        )
    )
    # Long enough for the spawn to have happened, short enough to keep the
    # test quick — asserted rather than assumed just below.
    for _ in range(200):
        if spawned:
            break
        await asyncio.sleep(0.01)
    assert spawned, "the transcode never spawned a child process"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    proc = spawned[0]
    # Reaped, not merely signalled: a returncode means the child was
    # waited for, so nothing is left as a zombie either.
    assert proc.returncode is not None, "the ffmpeg child outlived the cancelled transcode"


async def test_a_cancelled_job_leaves_a_failed_row_not_a_stuck_one(  # type: ignore[no-untyped-def]
    monkeypatch, settings, database_url
) -> None:
    """The asset used to stay `transcoding` for ever, and the operations
    screen lists only failed jobs — so the one screen meant to surface a
    broken transcode was the one place it could never appear."""
    if not _database_reachable(settings.database_url):
        pytest.skip("no Postgres on the configured DATABASE_URL")

    init_engine(settings)
    from src.core.db import get_sessionmaker

    factory = get_sessionmaker()
    real_settings = Settings()
    storage = get_storage_adapter(real_settings)

    asset_id = uuid7()
    source_key = f"video-assets/{asset_id}/source"
    await storage.ensure_container(Container.PRIVATE_CONTENT)
    await storage.upload_object(Container.PRIVATE_CONTENT, source_key, b"not really a video")

    async with factory() as session:
        session.add(VideoAsset(id=asset_id, source_object_key=source_key, state="uploaded"))
        await session.commit()

    async def fake_probe(*args: object, **kwargs: object) -> ProbeResult:
        return ProbeResult(duration_seconds=600.0, has_audio=True, fps=25.0)

    started = asyncio.Event()

    async def fake_run_transcode(*args: object, **kwargs: object) -> None:
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(ffmpeg_service, "probe_source", fake_probe)
    monkeypatch.setattr(pipeline_module, "run_transcode", fake_run_transcode)

    async def run() -> None:
        async with factory() as session:
            await pipeline_module.transcode_video_asset(
                session, storage, real_settings, video_asset_id=asset_id
            )

    task = asyncio.create_task(run())
    await asyncio.wait_for(started.wait(), timeout=10)

    # A real task cancellation, which is what arq's timeout does — not a
    # CancelledError raised inline. That difference is the whole reason
    # the commit in the handler is shielded: without the shield the
    # rollback would be the last thing to happen and the row would stay
    # stuck regardless.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with factory() as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT v.state, j.state, j.error, j.finished_at "
                    "FROM video_assets v JOIN transcode_jobs j ON j.id = v.transcode_job_id "
                    "WHERE v.id = :i"
                ),
                {"i": asset_id},
            )
        ).first()

    assert row is not None, "the job row was never written"
    asset_state, job_state, error, finished_at = row
    assert asset_state == "failed", f"asset left in {asset_state!r}"
    # "failed", not "error": services/operations.py queries this column
    # for the operations screen's needs-attention list, and the two
    # spellings never matched.
    assert job_state == "failed", f"job left in {job_state!r}"
    assert error and "cancelled" in error.lower()
    assert finished_at is not None

    async with factory() as session:
        await session.execute(sa.text("DELETE FROM video_assets WHERE id = :i"), {"i": asset_id})
        await session.commit()

    await dispose_engine()


def test_the_normal_failure_path_uses_the_same_spelling() -> None:
    """One constant, used by the two places the pipeline records a
    failure, matching what `services/operations.py` looks for."""
    assert pipeline_module.FAILED_STATE == "failed"
    source = (
        Path(__file__).resolve().parents[1] / "src" / "services" / "media" / "pipeline.py"
    ).read_text(encoding="utf-8")
    assert 'job.state = "error"' not in source
    assert source.count("job.state = FAILED_STATE") == 2
