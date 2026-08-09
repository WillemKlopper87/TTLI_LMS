"""The storage interface. One contract, three implementations.

06_OPERATIONS.md §2.1: `S3StorageAdapter` · `AzureBlobStorageAdapter` ·
`LocalStorageAdapter`, chosen by `STORAGE_BACKEND` so the customer's hosting
preference is configuration, not architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class Container:
    """§2.2's classification. Never mix these in one bucket — a single
    bucket with mixed ACLs is how private content becomes public."""

    PUBLIC_MARKETING = "public-marketing"
    PRIVATE_CONTENT = "private-content"
    USER_UPLOADS = "user-uploads"
    GENERATED_DOCUMENTS = "generated-documents"
    BACKUPS = "backups"

    ALL = (PUBLIC_MARKETING, PRIVATE_CONTENT, USER_UPLOADS, GENERATED_DOCUMENTS, BACKUPS)
    PUBLIC = (PUBLIC_MARKETING,)


@dataclass(frozen=True, slots=True)
class StorageObject:
    key: str
    size: int
    content_type: str | None
    last_modified: datetime


class StorageError(Exception):
    """Wraps a backend-specific failure so callers depend on one exception
    type, not on boto3's, Azure's and the filesystem's each separately."""


class ObjectNotFound(StorageError):
    pass


class StorageService(ABC):
    @abstractmethod
    async def ensure_container(self, container: str) -> None:
        """Idempotent setup — a local directory, an S3 bucket, an Azure
        container. Not in the documented 8-method interface; added because
        every adapter needs it for local/dev bootstrap and tests."""

    @abstractmethod
    async def upload_object(
        self,
        container: str,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None: ...

    @abstractmethod
    async def get_object(self, container: str, key: str) -> bytes:
        """Raises ObjectNotFound if the key does not exist."""

    @abstractmethod
    async def delete_object(self, container: str, key: str) -> None: ...

    @abstractmethod
    async def generate_signed_url(
        self, container: str, key: str, *, expires_in: int, method: str = "GET"
    ) -> str:
        """A time-limited URL for `private-content`, `user-uploads`,
        `generated-documents` and `backups` — never for public-marketing,
        which has a stable public URL instead."""

    @abstractmethod
    async def get_public_url(self, container: str, key: str) -> str:
        """Only ever valid for Container.PUBLIC_MARKETING — implementations
        must refuse any other container (§2.2: "Never public: premium course
        content, personal data, invoices, certificates, user uploads")."""

    @abstractmethod
    async def set_metadata(self, container: str, key: str, metadata: dict[str, str]) -> None: ...

    @abstractmethod
    async def list_objects(self, container: str, prefix: str = "") -> list[StorageObject]: ...

    @abstractmethod
    async def apply_lifecycle_policy(self, container: str, *, expire_after_days: int) -> None: ...


def require_public_container(container: str) -> None:
    if container not in Container.PUBLIC:
        raise StorageError(
            f"{container!r} is not a public container; get_public_url is only valid for "
            f"{Container.PUBLIC_MARKETING!r}"
        )


__all__ = [
    "Container",
    "ObjectNotFound",
    "StorageError",
    "StorageObject",
    "StorageService",
    "require_public_container",
]
