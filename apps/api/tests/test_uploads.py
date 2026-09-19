"""Shared upload-size guard (M3): every upload endpoint in this app read
its whole request body into memory via a bare `await file.read()` before
any size check ever ran — a multi-GB body is buffered to completion
first regardless of what limit the endpoint eventually enforces. No
database or network needed: this is pure stream-chunking logic against
an in-memory UploadFile.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from src.core.errors import PayloadTooLarge
from src.core.uploads import read_upload_within_limit


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="test")


async def test_reads_a_file_under_the_limit() -> None:
    data = b"x" * 100
    result = await read_upload_within_limit(_upload(data), max_bytes=200)
    assert result == data


async def test_refuses_a_file_over_the_limit_without_buffering_past_it() -> None:
    data = b"x" * 300
    with pytest.raises(PayloadTooLarge):
        await read_upload_within_limit(_upload(data), max_bytes=200, chunk_size=64)


async def test_a_file_exactly_at_the_limit_is_accepted() -> None:
    data = b"x" * 200
    result = await read_upload_within_limit(_upload(data), max_bytes=200)
    assert result == data
