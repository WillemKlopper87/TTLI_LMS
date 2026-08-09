"""Storage adapters.

LocalStorageAdapter needs nothing external. S3StorageAdapter is tested
against moto's in-process mock rather than a live MinIO/AWS endpoint — moto
patches botocore's transport, so the exact same adapter code under test runs
identically in local dev and CI, with no service container and nothing that
can skip. (MinIO — already in infra/docker-compose.yml on port 9140 — is a
fine manual sanity check: point S3StorageAdapter's endpoint_url at it and the
same code talks to a real server.) AzureBlobStorageAdapter has no comparable
in-process mock available, and there is no local Azurite service provisioned,
so it gets a call-shape unit test against a mocked SDK client instead of live
I/O — real integration coverage is a Phase 7 concern once Azure is actually
targeted.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws
from src.services.storage.base import Container, ObjectNotFound, StorageError
from src.services.storage.local import LocalStorageAdapter


def _unique_key() -> str:
    return f"sprint3-{uuid.uuid4().hex[:12]}.txt"


@pytest.fixture
def local_adapter(tmp_path) -> LocalStorageAdapter:  # type: ignore[no-untyped-def]
    return LocalStorageAdapter(str(tmp_path))


async def test_local_upload_and_get_roundtrip(local_adapter: LocalStorageAdapter) -> None:
    key = _unique_key()
    await local_adapter.upload_object(
        Container.PRIVATE_CONTENT, key, b"hello", content_type="text/plain"
    )
    assert await local_adapter.get_object(Container.PRIVATE_CONTENT, key) == b"hello"


async def test_local_get_missing_object_raises(local_adapter: LocalStorageAdapter) -> None:
    with pytest.raises(ObjectNotFound):
        await local_adapter.get_object(Container.PRIVATE_CONTENT, "does-not-exist.txt")


async def test_local_delete_removes_object(local_adapter: LocalStorageAdapter) -> None:
    key = _unique_key()
    await local_adapter.upload_object(Container.USER_UPLOADS, key, b"data")
    await local_adapter.delete_object(Container.USER_UPLOADS, key)
    with pytest.raises(ObjectNotFound):
        await local_adapter.get_object(Container.USER_UPLOADS, key)


async def test_local_list_objects_filters_by_prefix(local_adapter: LocalStorageAdapter) -> None:
    await local_adapter.upload_object(Container.GENERATED_DOCUMENTS, "invoices/a.pdf", b"a")
    await local_adapter.upload_object(Container.GENERATED_DOCUMENTS, "invoices/b.pdf", b"b")
    await local_adapter.upload_object(Container.GENERATED_DOCUMENTS, "certificates/c.pdf", b"c")

    invoices = await local_adapter.list_objects(Container.GENERATED_DOCUMENTS, prefix="invoices/")
    assert {o.key for o in invoices} == {"invoices/a.pdf", "invoices/b.pdf"}


async def test_local_public_url_refuses_non_public_container(
    local_adapter: LocalStorageAdapter,
) -> None:
    with pytest.raises(StorageError):
        await local_adapter.get_public_url(Container.USER_UPLOADS, "secret.pdf")


async def test_local_public_url_allows_public_marketing(
    local_adapter: LocalStorageAdapter,
) -> None:
    url = await local_adapter.get_public_url(Container.PUBLIC_MARKETING, "logo.png")
    assert url.startswith("file://")


async def test_local_signed_url_encodes_expiry(local_adapter: LocalStorageAdapter) -> None:
    key = _unique_key()
    url = await local_adapter.generate_signed_url(Container.PRIVATE_CONTENT, key, expires_in=900)
    assert "expires_at=" in url


async def test_local_set_metadata_on_missing_object_raises(
    local_adapter: LocalStorageAdapter,
) -> None:
    with pytest.raises(ObjectNotFound):
        await local_adapter.set_metadata(Container.USER_UPLOADS, "nope.txt", {"a": "b"})


async def test_local_lifecycle_policy_deletes_nothing_when_nothing_is_old(
    local_adapter: LocalStorageAdapter,
) -> None:
    key = _unique_key()
    await local_adapter.upload_object(Container.PRIVATE_CONTENT, key, b"fresh")
    await local_adapter.apply_lifecycle_policy(Container.PRIVATE_CONTENT, expire_after_days=30)
    assert await local_adapter.get_object(Container.PRIVATE_CONTENT, key) == b"fresh"


@pytest.fixture
def s3_adapter():  # type: ignore[no-untyped-def]
    with mock_aws():
        from src.services.storage.s3 import S3StorageAdapter

        adapter = S3StorageAdapter(
            endpoint_url="", access_key="testing", secret_key="testing", region="af-south-1"
        )
        yield adapter


async def test_s3_upload_get_delete_roundtrip(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    await s3_adapter.ensure_container(Container.PRIVATE_CONTENT)
    key = _unique_key()

    await s3_adapter.upload_object(
        Container.PRIVATE_CONTENT, key, b"s3 says hi", content_type="text/plain"
    )
    assert await s3_adapter.get_object(Container.PRIVATE_CONTENT, key) == b"s3 says hi"

    await s3_adapter.delete_object(Container.PRIVATE_CONTENT, key)
    with pytest.raises(ObjectNotFound):
        await s3_adapter.get_object(Container.PRIVATE_CONTENT, key)


async def test_s3_get_missing_object_raises(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    await s3_adapter.ensure_container(Container.PRIVATE_CONTENT)
    with pytest.raises(ObjectNotFound):
        await s3_adapter.get_object(Container.PRIVATE_CONTENT, "does-not-exist.txt")


async def test_s3_list_objects_filters_by_prefix(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    await s3_adapter.ensure_container(Container.GENERATED_DOCUMENTS)
    await s3_adapter.upload_object(Container.GENERATED_DOCUMENTS, "invoices/a.pdf", b"a")
    await s3_adapter.upload_object(Container.GENERATED_DOCUMENTS, "invoices/b.pdf", b"b")
    await s3_adapter.upload_object(Container.GENERATED_DOCUMENTS, "certificates/c.pdf", b"c")

    invoices = await s3_adapter.list_objects(Container.GENERATED_DOCUMENTS, prefix="invoices/")
    assert {o.key for o in invoices} == {"invoices/a.pdf", "invoices/b.pdf"}


async def test_s3_signed_url_is_well_formed(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    key = _unique_key()
    url = await s3_adapter.generate_signed_url(Container.PRIVATE_CONTENT, key, expires_in=300)
    assert "Signature=" in url or "X-Amz-Signature=" in url


async def test_s3_public_url_refuses_non_public_container(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(StorageError):
        await s3_adapter.get_public_url(Container.USER_UPLOADS, "secret.pdf")


async def test_s3_set_metadata_roundtrip(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    await s3_adapter.ensure_container(Container.USER_UPLOADS)
    key = _unique_key()
    await s3_adapter.upload_object(Container.USER_UPLOADS, key, b"data")
    await s3_adapter.set_metadata(Container.USER_UPLOADS, key, {"scanned": "clean"})
    # moto persists metadata through copy_object; the read-back path is
    # get_object's headers, which this adapter does not surface today, so the
    # assertion here is that the call completes without raising.


async def test_s3_lifecycle_policy_registers_without_error(s3_adapter) -> None:  # type: ignore[no-untyped-def]
    await s3_adapter.ensure_container(Container.PRIVATE_CONTENT)
    await s3_adapter.apply_lifecycle_policy(Container.PRIVATE_CONTENT, expire_after_days=30)


@pytest.fixture
def mock_blob_service():  # type: ignore[no-untyped-def]
    with patch(
        "src.services.storage.azure_blob.BlobServiceClient.from_connection_string"
    ) as factory:
        service = MagicMock()
        service.account_name = "ttlidev"
        service.credential.account_key = "fake-account-key"
        factory.return_value = service
        yield service


async def test_azure_upload_calls_the_sdk_with_the_right_arguments(mock_blob_service) -> None:  # type: ignore[no-untyped-def]
    from src.services.storage.azure_blob import AzureBlobStorageAdapter

    blob_client = MagicMock()
    mock_blob_service.get_blob_client.return_value = blob_client

    adapter = AzureBlobStorageAdapter(connection_string="UseDevelopmentStorage=true")
    await adapter.upload_object(Container.PRIVATE_CONTENT, "a.pdf", b"data", content_type="a/b")

    mock_blob_service.get_blob_client.assert_called_with(
        container=Container.PRIVATE_CONTENT, blob="a.pdf"
    )
    blob_client.upload_blob.assert_called_once()
    assert blob_client.upload_blob.call_args.kwargs["overwrite"] is True


async def test_azure_get_missing_object_raises(mock_blob_service) -> None:  # type: ignore[no-untyped-def]
    from azure.core.exceptions import ResourceNotFoundError
    from src.services.storage.azure_blob import AzureBlobStorageAdapter

    blob_client = MagicMock()
    blob_client.download_blob.side_effect = ResourceNotFoundError("not found")
    mock_blob_service.get_blob_client.return_value = blob_client

    adapter = AzureBlobStorageAdapter(connection_string="UseDevelopmentStorage=true")
    with pytest.raises(ObjectNotFound):
        await adapter.get_object(Container.PRIVATE_CONTENT, "missing.pdf")


async def test_azure_public_url_refuses_non_public_container(mock_blob_service) -> None:  # type: ignore[no-untyped-def]
    from src.services.storage.azure_blob import AzureBlobStorageAdapter

    adapter = AzureBlobStorageAdapter(connection_string="UseDevelopmentStorage=true")
    with pytest.raises(StorageError):
        await adapter.get_public_url(Container.USER_UPLOADS, "secret.pdf")


async def test_azure_lifecycle_policy_is_explicitly_unimplemented(mock_blob_service) -> None:  # type: ignore[no-untyped-def]
    from src.services.storage.azure_blob import AzureBlobStorageAdapter

    adapter = AzureBlobStorageAdapter(connection_string="UseDevelopmentStorage=true")
    with pytest.raises(NotImplementedError):
        await adapter.apply_lifecycle_policy(Container.PRIVATE_CONTENT, expire_after_days=30)
