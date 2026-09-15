"""Metrics wrapper around the storage adapter contract.

Instrument the one shared boundary instead of sprinkling counters through every
caller. Object keys are deliberately never labels: keys routinely contain user
or tenant identifiers and would also create unbounded metric cardinality.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from src.core.metrics import STORAGE_OPERATIONS
from src.services.storage.base import ObjectNotFound, StorageObject, StorageService

T = TypeVar("T")


class ObservedStorageService(StorageService):
    def __init__(self, inner: StorageService, *, backend: str) -> None:
        self._inner = inner
        self._backend = backend

    async def _observe(
        self, operation: str, container: str, call: Callable[[], Awaitable[T]]
    ) -> T:
        try:
            result = await call()
        except ObjectNotFound:
            STORAGE_OPERATIONS.labels(self._backend, operation, container, "not_found").inc()
            raise
        except Exception:
            STORAGE_OPERATIONS.labels(self._backend, operation, container, "error").inc()
            raise
        else:
            STORAGE_OPERATIONS.labels(self._backend, operation, container, "ok").inc()
            return result

    async def ensure_container(self, container: str) -> None:
        await self._observe("ensure_container", container, lambda: self._inner.ensure_container(container))

    async def upload_object(
        self,
        container: str,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        await self._observe(
            "upload_object",
            container,
            lambda: self._inner.upload_object(
                container,
                key,
                data,
                content_type=content_type,
                metadata=metadata,
            ),
        )

    async def get_object(self, container: str, key: str) -> bytes:
        return await self._observe("get_object", container, lambda: self._inner.get_object(container, key))

    async def delete_object(self, container: str, key: str) -> None:
        await self._observe(
            "delete_object", container, lambda: self._inner.delete_object(container, key)
        )

    async def generate_signed_url(
        self, container: str, key: str, *, expires_in: int, method: str = "GET"
    ) -> str:
        return await self._observe(
            "generate_signed_url",
            container,
            lambda: self._inner.generate_signed_url(
                container, key, expires_in=expires_in, method=method
            ),
        )

    async def get_public_url(self, container: str, key: str) -> str:
        return await self._observe(
            "get_public_url", container, lambda: self._inner.get_public_url(container, key)
        )

    async def set_metadata(self, container: str, key: str, metadata: dict[str, str]) -> None:
        await self._observe(
            "set_metadata",
            container,
            lambda: self._inner.set_metadata(container, key, metadata),
        )

    async def list_objects(self, container: str, prefix: str = "") -> list[StorageObject]:
        return await self._observe(
            "list_objects", container, lambda: self._inner.list_objects(container, prefix)
        )

    async def apply_lifecycle_policy(self, container: str, *, expire_after_days: int) -> None:
        await self._observe(
            "apply_lifecycle_policy",
            container,
            lambda: self._inner.apply_lifecycle_policy(
                container, expire_after_days=expire_after_days
            ),
        )


__all__ = ["ObservedStorageService"]
