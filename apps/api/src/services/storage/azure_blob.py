"""Azure Blob storage — the customer's other named hosting preference
(01_PRD.md §5). Same asyncio.to_thread wrapping as s3.py: the official SDK's
sync client, not the aio variant, to keep one dependency pattern across every
adapter rather than mixing sync-wrapped and natively-async clients.

No local emulator is wired up for this one (Azurite would need adding to
infra/docker-compose.yml, and there is no equivalent to MinIO already
provisioned for it) — see tests/test_storage.py, which skips its Azure cases
when AZURE_STORAGE_CONNECTION_STRING is unset rather than pretending to cover
a path nothing here actually exercises.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    PublicAccess,
    generate_blob_sas,
)

from src.services.storage.base import (
    Container,
    ObjectNotFound,
    StorageError,
    StorageObject,
    StorageService,
    require_public_container,
)


class AzureBlobStorageAdapter(StorageService):
    def __init__(self, *, connection_string: str) -> None:
        self._service = BlobServiceClient.from_connection_string(connection_string)

    async def ensure_container(self, container: str) -> None:
        public_access = PublicAccess.BLOB if container == Container.PUBLIC_MARKETING else None

        def _create() -> None:
            try:
                self._service.create_container(container, public_access=public_access)
            except ResourceExistsError:
                pass

        await asyncio.to_thread(_create)

    async def upload_object(
        self,
        container: str,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        blob = self._service.get_blob_client(container=container, blob=key)
        settings = ContentSettings(content_type=content_type) if content_type else None
        await asyncio.to_thread(
            blob.upload_blob,
            data,
            overwrite=True,
            content_settings=settings,
            metadata=metadata or {},
        )

    async def get_object(self, container: str, key: str) -> bytes:
        blob = self._service.get_blob_client(container=container, blob=key)

        def _get() -> bytes:
            try:
                result: bytes = blob.download_blob().readall()
                return result
            except ResourceNotFoundError as exc:
                raise ObjectNotFound(f"{container}/{key} does not exist") from exc

        return await asyncio.to_thread(_get)

    async def delete_object(self, container: str, key: str) -> None:
        blob = self._service.get_blob_client(container=container, blob=key)
        await asyncio.to_thread(blob.delete_blob)

    async def generate_signed_url(
        self, container: str, key: str, *, expires_in: int, method: str = "GET"
    ) -> str:
        blob = self._service.get_blob_client(container=container, blob=key)
        credential = self._service.credential
        account_key = getattr(credential, "account_key", None)
        account_name = self._service.account_name
        if account_key is None or account_name is None:
            raise StorageError(
                "generate_signed_url needs an account-key credential; "
                "the configured connection string does not carry one"
            )

        permission = (
            BlobSasPermissions(write=True)
            if method.upper() == "PUT"
            else BlobSasPermissions(read=True)
        )

        def _sign() -> str:
            sas = generate_blob_sas(
                account_name=account_name,
                container_name=container,
                blob_name=key,
                account_key=account_key,
                permission=permission,
                expiry=datetime.now(UTC) + timedelta(seconds=expires_in),
            )
            return f"{blob.url}?{sas}"

        return await asyncio.to_thread(_sign)

    async def get_public_url(self, container: str, key: str) -> str:
        require_public_container(container)
        blob = self._service.get_blob_client(container=container, blob=key)
        return blob.url

    async def set_metadata(self, container: str, key: str, metadata: dict[str, str]) -> None:
        blob = self._service.get_blob_client(container=container, blob=key)

        def _set() -> None:
            try:
                blob.set_blob_metadata(metadata)
            except ResourceNotFoundError as exc:
                raise ObjectNotFound(f"{container}/{key} does not exist") from exc

        await asyncio.to_thread(_set)

    async def list_objects(self, container: str, prefix: str = "") -> list[StorageObject]:
        container_client = self._service.get_container_client(container)

        def _list() -> list[StorageObject]:
            results = []
            for item in container_client.list_blobs(name_starts_with=prefix):
                content_type = item.content_settings.content_type if item.content_settings else None
                results.append(
                    StorageObject(
                        key=item.name,
                        size=item.size or 0,
                        content_type=content_type,
                        last_modified=item.last_modified,
                    )
                )
            return results

        return await asyncio.to_thread(_list)

    async def apply_lifecycle_policy(self, container: str, *, expire_after_days: int) -> None:
        raise NotImplementedError(
            "Azure Blob lifecycle rules are an account-level, control-plane "
            "operation (azure-mgmt-storage, ARM credentials) — out of scope "
            "for this data-plane adapter. Configure it via Terraform in "
            "Phase 7 (06_OPERATIONS.md §4.2), not at runtime."
        )


__all__ = ["AzureBlobStorageAdapter"]
