from __future__ import annotations

from pydantic import BaseModel


class FeatureFlagInfo(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool


class FeatureFlagsResponse(BaseModel):
    flags: list[FeatureFlagInfo]


class SetFeatureFlagRequest(BaseModel):
    enabled: bool


class ServiceStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class SystemHealthResponse(BaseModel):
    api_version: str
    environment: str
    services: list[ServiceStatus]
