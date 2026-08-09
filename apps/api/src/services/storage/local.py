"""Filesystem-backed storage. Zero external services — the adapter a fresh
clone gets by default (STORAGE_BACKEND=local) before Docker Compose is even
running. Point STORAGE_BACKEND at "s3" with S3_ENDPOINT_URL set to the
already-provisioned MinIO container to exercise S3StorageAdapter locally
instead; see infra/docker-compose.yml.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.services.storage.base import (
    Container,
    ObjectNotFound,
    StorageError,
    StorageObject,
    StorageService,
    require_public_container,
)

_META_SUFFIX = ".meta.json"


class LocalStorageAdapter(StorageService):
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _container_dir(self, container: str) -> Path:
        if container not in Container.ALL:
            raise StorageError(f"unknown container {container!r}")
        return self._root / container

    def _object_path(self, container: str, key: str) -> Path:
        if ".." in Path(key).parts:
            raise StorageError(f"invalid key {key!r}")
        return self._container_dir(container) / key

    async def ensure_container(self, container: str) -> None:
        await asyncio.to_thread(self._container_dir(container).mkdir, parents=True, exist_ok=True)

    async def upload_object(
        self,
        container: str,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        path = self._object_path(container, key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            meta_path = path.with_name(path.name + _META_SUFFIX)
            meta_path.write_text(
                json.dumps({"content_type": content_type, "metadata": metadata or {}}),
                encoding="utf-8",
            )

        await asyncio.to_thread(_write)

    async def get_object(self, container: str, key: str) -> bytes:
        path = self._object_path(container, key)
        if not await asyncio.to_thread(path.is_file):
            raise ObjectNotFound(f"{container}/{key} does not exist")
        result: bytes = await asyncio.to_thread(path.read_bytes)
        return result

    async def delete_object(self, container: str, key: str) -> None:
        path = self._object_path(container, key)

        def _delete() -> None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + _META_SUFFIX).unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def generate_signed_url(
        self, container: str, key: str, *, expires_in: int, method: str = "GET"
    ) -> str:
        """Not a fetchable HTTP URL — there is no local file-serving route
        yet (that lands with the Phase 4 media pipeline). Callers in tests
        and Sprint 3 code can still assert on the container/key/expiry it
        encodes.
        """
        path = self._object_path(container, key)
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        return f"file://{path.resolve()}?method={method}&expires_at={expires_at.isoformat()}"

    async def get_public_url(self, container: str, key: str) -> str:
        require_public_container(container)
        path = self._object_path(container, key)
        return f"file://{path.resolve()}"

    async def set_metadata(self, container: str, key: str, metadata: dict[str, str]) -> None:
        path = self._object_path(container, key)
        meta_path = path.with_name(path.name + _META_SUFFIX)

        def _update() -> None:
            if meta_path.exists():
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                existing = {"content_type": None, "metadata": {}}
            existing["metadata"] = metadata
            meta_path.write_text(json.dumps(existing), encoding="utf-8")

        if not await asyncio.to_thread(path.is_file):
            raise ObjectNotFound(f"{container}/{key} does not exist")
        await asyncio.to_thread(_update)

    async def list_objects(self, container: str, prefix: str = "") -> list[StorageObject]:
        container_dir = self._container_dir(container)

        def _list() -> list[StorageObject]:
            if not container_dir.is_dir():
                return []
            results = []
            for path in sorted(container_dir.rglob("*")):
                if not path.is_file() or path.name.endswith(_META_SUFFIX):
                    continue
                rel_key = path.relative_to(container_dir).as_posix()
                if not rel_key.startswith(prefix):
                    continue
                meta_path = path.with_name(path.name + _META_SUFFIX)
                content_type = None
                if meta_path.exists():
                    content_type = json.loads(meta_path.read_text(encoding="utf-8")).get(
                        "content_type"
                    )
                stat = path.stat()
                results.append(
                    StorageObject(
                        key=rel_key,
                        size=stat.st_size,
                        content_type=content_type,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )
            return results

        return await asyncio.to_thread(_list)

    async def apply_lifecycle_policy(self, container: str, *, expire_after_days: int) -> None:
        """No background daemon exists for the local adapter, so this sweeps
        immediately rather than registering a policy for later enforcement —
        the honest local equivalent of what S3/Azure do asynchronously."""
        cutoff = datetime.now(UTC) - timedelta(days=expire_after_days)
        for obj in await self.list_objects(container):
            if obj.last_modified < cutoff:
                await self.delete_object(container, obj.key)


__all__ = ["LocalStorageAdapter"]
