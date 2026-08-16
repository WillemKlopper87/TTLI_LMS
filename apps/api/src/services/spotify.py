"""Spotify episode metadata lookup (REQ-STORE-04) — admin convenience
only: paste an episode URL, prefill title/description/duration/artwork
in the curation form. Client-credentials flow (app-only, no user OAuth,
no scopes) since this never acts on behalf of a Spotify user.

Written the same way `services/payments/payfast.py` was: real code,
graceful degradation when unconfigured (`settings.spotify_client_id`
empty), no live credentials on file to verify the actual token exchange
against. Low call volume (an admin pasting a URL occasionally, not a
checkout flow) is why this fetches a fresh access token per lookup
rather than caching one in Redis — simpler, and the extra round-trip is
immaterial at this frequency.
"""

from __future__ import annotations

import base64
import re

import httpx

from src.core.config import Settings

_EPISODE_URL_RE = re.compile(r"open\.spotify\.com(?:/intl-\w+)?/episode/([a-zA-Z0-9]+)")
_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - a URL, not a credential
_EPISODE_URL = "https://api.spotify.com/v1/episodes/{id}"


class SpotifyLookupResult:
    def __init__(
        self,
        *,
        embed_id: str,
        title: str,
        description: str | None,
        duration_seconds: int,
        cover_image_url: str | None,
    ) -> None:
        self.embed_id = embed_id
        self.title = title
        self.description = description
        self.duration_seconds = duration_seconds
        self.cover_image_url = cover_image_url


class SpotifyLookupError(Exception):
    """A configured lookup that still failed — a bad URL, an episode
    Spotify won't return, or a network/API error. Callers should surface
    this as a clear "couldn't look that up" message, not a 500."""


def parse_episode_id(url: str) -> str | None:
    match = _EPISODE_URL_RE.search(url)
    return match.group(1) if match else None


async def lookup_episode(url: str, *, settings: Settings) -> SpotifyLookupResult | None:
    """Returns None if no Spotify credentials are configured for this
    deployment — the caller's job to render that as "not configured,
    enter manually," not an error."""
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        return None

    embed_id = parse_episode_id(url)
    if embed_id is None:
        raise SpotifyLookupError("That doesn't look like a Spotify episode URL.")

    credentials = base64.b64encode(
        f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    ).decode()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]

            episode_resp = await client.get(
                _EPISODE_URL.format(id=embed_id),
                params={"market": "US"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            episode_resp.raise_for_status()
            episode = episode_resp.json()
    except httpx.HTTPError as exc:
        raise SpotifyLookupError(f"Spotify lookup failed: {exc}") from exc

    images = episode.get("images") or []
    return SpotifyLookupResult(
        embed_id=embed_id,
        title=episode["name"],
        description=episode.get("description"),
        duration_seconds=int(episode.get("duration_ms", 0) / 1000),
        cover_image_url=images[0]["url"] if images else None,
    )


__all__ = ["SpotifyLookupError", "SpotifyLookupResult", "lookup_episode", "parse_episode_id"]
