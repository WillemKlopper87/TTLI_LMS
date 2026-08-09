from __future__ import annotations

from src.core.config import Settings
from src.services.storage.base import (
    Container,
    ObjectNotFound,
    StorageError,
    StorageObject,
    StorageService,
)


def get_storage_adapter(settings: Settings) -> StorageService:
    if settings.storage_backend == "local":
        from src.services.storage.local import LocalStorageAdapter

        return LocalStorageAdapter(settings.storage_local_root)

    if settings.storage_backend == "s3":
        from src.services.storage.s3 import S3StorageAdapter

        return S3StorageAdapter(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )

    from src.services.storage.azure_blob import AzureBlobStorageAdapter

    return AzureBlobStorageAdapter(connection_string=settings.azure_storage_connection_string)


__all__ = [
    "Container",
    "ObjectNotFound",
    "StorageError",
    "StorageObject",
    "StorageService",
    "get_storage_adapter",
]
