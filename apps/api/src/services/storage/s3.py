"""S3-protocol storage. Works against real AWS S3 (leave S3_ENDPOINT_URL
unset) or the MinIO container already in infra/docker-compose.yml
(S3_ENDPOINT_URL=http://localhost:9140) — MinIO speaks the S3 API, so the
same adapter code exercises the real request/response shapes locally without
ever touching AWS. boto3 is synchronous; every call is wrapped in
asyncio.to_thread rather than pulling in aioboto3's aiohttp-based stack for
a Phase 1 workload that is not request-rate sensitive here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from src.services.storage.base import (
    ObjectNotFound,
    StorageError,
    StorageObject,
    StorageService,
    require_public_container,
)


class S3StorageAdapter(StorageService):
    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        self._endpoint_url = endpoint_url or None
        self._region = region
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            # Path-style addressing: MinIO and bucket names containing
            # hyphens (public-marketing, ...) do not play well with
            # virtual-hosted-style addressing against a custom endpoint.
            config=Config(s3={"addressing_style": "path"}),
        )

    async def ensure_container(self, container: str) -> None:
        def _create() -> None:
            kwargs: dict[str, object] = {"Bucket": container}
            # us-east-1 is the one region that rejects an explicit
            # LocationConstraint; every other region — including af-south-1,
            # the target region (01_PRD.md §5) — requires one.
            if self._region and self._region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
            try:
                self._client.create_bucket(**kwargs)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                    raise StorageError(str(exc)) from exc

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
        def _put() -> None:
            kwargs: dict[str, object] = {"Bucket": container, "Key": key, "Body": data}
            if content_type:
                kwargs["ContentType"] = content_type
            if metadata:
                kwargs["Metadata"] = metadata
            self._client.put_object(**kwargs)

        await asyncio.to_thread(_put)

    async def get_object(self, container: str, key: str) -> bytes:
        def _get() -> bytes:
            try:
                body: bytes = self._client.get_object(Bucket=container, Key=key)["Body"].read()
                return body
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404"}:
                    raise ObjectNotFound(f"{container}/{key} does not exist") from exc
                raise StorageError(str(exc)) from exc

        return await asyncio.to_thread(_get)

    async def delete_object(self, container: str, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=container, Key=key)

    async def generate_signed_url(
        self, container: str, key: str, *, expires_in: int, method: str = "GET"
    ) -> str:
        operation = "put_object" if method.upper() == "PUT" else "get_object"

        def _presign() -> str:
            url: str = self._client.generate_presigned_url(
                operation,
                Params={"Bucket": container, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

        return await asyncio.to_thread(_presign)

    async def get_public_url(self, container: str, key: str) -> str:
        require_public_container(container)
        if self._endpoint_url:
            return f"{self._endpoint_url}/{container}/{key}"
        return f"https://{container}.s3.{self._region}.amazonaws.com/{key}"

    async def set_metadata(self, container: str, key: str, metadata: dict[str, str]) -> None:
        def _copy() -> None:
            try:
                self._client.copy_object(
                    Bucket=container,
                    CopySource={"Bucket": container, "Key": key},
                    Key=key,
                    Metadata=metadata,
                    MetadataDirective="REPLACE",
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404"}:
                    raise ObjectNotFound(f"{container}/{key} does not exist") from exc
                raise StorageError(str(exc)) from exc

        await asyncio.to_thread(_copy)

    async def list_objects(self, container: str, prefix: str = "") -> list[StorageObject]:
        def _list() -> list[StorageObject]:
            paginator = self._client.get_paginator("list_objects_v2")
            results: list[StorageObject] = []
            for page in paginator.paginate(Bucket=container, Prefix=prefix):
                for item in page.get("Contents", []):
                    last_modified = item["LastModified"]
                    if last_modified.tzinfo is None:
                        last_modified = last_modified.replace(tzinfo=UTC)
                    results.append(
                        StorageObject(
                            key=item["Key"],
                            size=item["Size"],
                            content_type=None,
                            last_modified=last_modified,
                        )
                    )
            return results

        return await asyncio.to_thread(_list)

    async def apply_lifecycle_policy(self, container: str, *, expire_after_days: int) -> None:
        def _apply() -> None:
            self._client.put_bucket_lifecycle_configuration(
                Bucket=container,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "expire",
                            "Status": "Enabled",
                            "Filter": {"Prefix": ""},
                            "Expiration": {"Days": expire_after_days},
                        }
                    ]
                },
            )

        await asyncio.to_thread(_apply)


__all__ = ["S3StorageAdapter"]
