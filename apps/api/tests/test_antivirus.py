"""Virus scanning (04 §3, REQ-BYPASS-08). Runs against a real clamd, not a
mock — the same reason test_rls.py and test_storage.py's S3 path prefer a
real service; unlike MinIO, ClamAV needs no launch args, so it's a real CI
service container too (.github/workflows/api.yml).
"""

from __future__ import annotations

import socket

import pytest
from src.services import antivirus

pytestmark = pytest.mark.integration

# The EICAR standard antivirus test file: a harmless string every real
# antivirus engine (including ClamAV) is configured to flag by convention.
# Not an actual virus — see https://www.eicar.org/.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def _clamav_reachable(host: str, port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


@pytest.fixture(autouse=True)
def _require_clamav(settings):  # type: ignore[no-untyped-def]
    if not _clamav_reachable(settings.clamav_host, settings.clamav_port):
        pytest.skip(
            "no ClamAV on the configured CLAMAV_HOST/PORT — run: "
            "docker compose -f infra/docker-compose.yml up -d clamav"
        )


async def test_scan_clean_file_is_reported_clean(settings) -> None:  # type: ignore[no-untyped-def]
    result = await antivirus.scan(b"hello world, this is an ordinary file", settings=settings)
    assert result.clean is True
    assert result.signature is None


async def test_scan_eicar_test_file_is_flagged(settings) -> None:  # type: ignore[no-untyped-def]
    result = await antivirus.scan(EICAR, settings=settings)
    assert result.clean is False
    assert result.signature is not None
    assert "eicar" in result.signature.lower()


async def test_scan_unreachable_host_raises_scan_unavailable(settings) -> None:  # type: ignore[no-untyped-def]
    from src.core.config import Settings

    unreachable = Settings(**{**settings.model_dump(), "clamav_port": 1})
    with pytest.raises(antivirus.ScanUnavailable):
        await antivirus.scan(b"anything", settings=unreachable)
