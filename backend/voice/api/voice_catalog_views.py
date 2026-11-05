"""Read-only catalog endpoints (Mistral voices, etc.).

We proxy Mistral's voice catalog server-side so the React picker stays
in sync with whatever Mistral ships, instead of hard-coding a list that
goes stale. The key stays on the server; the response is cached so we
hit Mistral at most once per cache window.
"""

import logging
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from voice.constants import VOICE_BRAIN_MODELS

logger = logging.getLogger(__name__)

_MISTRAL_VOICES_URL = "https://api.mistral.ai/v1/audio/voices"
_CACHE_TTL_SECONDS = 60 * 60  # 1 hour
_CACHE_KEY = "voice:mistral_voices_catalog:v1"
# Mistral's /v1/audio/voices ignores `page`/`page_size` and uses `limit`
# (offset for paging). 200 is generous headroom over the ~30 voices today.
_FETCH_LIMIT = 200


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    """Pick the fields the FE needs and drop everything else."""
    langs = item.get("languages") or []
    primary = (langs[0] if langs else "").lower()
    if "_" in primary:
        lang, region = primary.split("_", 1)
        locale = f"{lang}-{region.upper()}"
    else:
        locale = primary.upper() or "?"
    tags = item.get("tags") or []
    return {
        "slug": item["slug"],
        "label": item.get("name") or item["slug"],
        "locale": locale,
        "gender": item.get("gender", ""),
        "description": ", ".join(tags),
        "tags": tags,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mistral_voices(request) -> Response:
    """Return the live Mistral voice catalog, cached server-side for 1 hour.

    Bypass the cache with ``?refresh=1`` if a freshly-shipped Mistral voice
    needs to appear before the TTL rolls over.
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None and request.query_params.get("refresh") != "1":
        return Response(cached)

    api_key = getattr(settings, "MISTRAL_API_KEY", "")
    if not api_key:
        return Response(
            {"error": "MISTRAL_API_KEY is not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        response = httpx.get(
            _MISTRAL_VOICES_URL,
            params={"limit": _FETCH_LIMIT},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Mistral voices proxy failed")
        return Response(
            {"error": "Failed to fetch Mistral voice catalog"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    voices = [_normalize(item) for item in response.json().get("items", [])]
    payload = {"voices": voices, "total": len(voices)}
    cache.set(_CACHE_KEY, payload, timeout=_CACHE_TTL_SECONDS)
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def brain_models(request) -> Response:
    """Return the brain (LLM) models a Mistral Voice agent can be configured with."""
    return Response({"models": VOICE_BRAIN_MODELS, "total": len(VOICE_BRAIN_MODELS)})
