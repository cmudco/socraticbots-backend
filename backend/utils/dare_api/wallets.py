"""
DARE wallet API client.

Pure pass-through proxy for the wallet endpoints we expose to socraticbots-frontend.
Nothing here transforms the response — DRF's ``djangorestframework-camel-case``
already serializes DARE responses in camelCase, and the SB → SB-react contract
expects the same shape.

Per the ``sb-dare-integration`` skill: do NOT re-camelize. Just forward the user's
JWT and stream the response back.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests
from rest_framework import status as drf_status

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


class DareWalletsClient(BaseDareApiClient):
    """Client for the DARE billing endpoints used by Socratic Bots."""

    REQUEST_TIMEOUT = 5

    def __init__(self, token: Optional[str] = None):
        super().__init__()
        self.token = token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                headers=self._get_headers(self.token),
                params=params,
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error('DARE wallet %s %s failed: %s', method, path, exc)
            raise DareApiError(f"Unable to reach DARE backend: {exc}")

        if response.status_code == drf_status.HTTP_204_NO_CONTENT:
            return {}
        try:
            body = response.json()
        except ValueError:
            raise DareApiError(
                'DARE returned a non-JSON response',
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise DareApiError(
                self._parse_dare_error(response),
                status_code=response.status_code,
                details=body if isinstance(body, dict) else None,
            )
        return body

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request('GET', path, params=params)

    def list_wallets(self) -> Dict[str, Any]:
        """Active wallet + the list of wallets visible to the caller."""
        return self._get('/api/billing/wallets/')

    def list_transactions(self, *, platform: Optional[str] = None,
                          billing_mode: Optional[str] = None) -> Dict[str, Any]:
        """Caller's transactions, defaulted to the Socratic Bots platform when
        called from this client (so the SB UI shows SB-attributed activity)."""
        params: Dict[str, Any] = {}
        if platform:
            params['platform'] = platform
        if billing_mode:
            params['billing_mode'] = billing_mode
        return self._get('/api/billing/transactions/', params=params)

    def effective_policy(self) -> Dict[str, Any]:
        """Resolved refill amount + period for the caller (USER → GROUP → SYSTEM)."""
        return self._get('/api/billing/effective-policy/')

    # ------------------------------------------------------------------
    # Wallet management — same endpoints DARE's own wallet popover uses
    # ------------------------------------------------------------------

    def set_active_wallet(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('PUT', '/api/billing/wallets/active/', payload=payload)

    def create_litellm_key(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('POST', '/api/billing/wallets/litellm/', payload=payload)

    def update_litellm_key(self, key_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            'PATCH', f'/api/billing/wallets/litellm/{key_id}/', payload=payload
        )

    def delete_litellm_key(self, key_id: str) -> Dict[str, Any]:
        return self._request('DELETE', f'/api/billing/wallets/litellm/{key_id}/')

    def test_unsaved_litellm_key(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            'POST', '/api/billing/wallets/litellm/test/', payload=payload
        )

    def test_saved_litellm_key(self, key_id: str) -> Dict[str, Any]:
        return self._request('POST', f'/api/billing/wallets/litellm/{key_id}/test/')

    def litellm_key_dependents(self, key_id: str) -> Dict[str, Any]:
        return self._get(f'/api/billing/wallets/litellm/{key_id}/dependents/')

    def provider_key_status(self) -> Dict[str, Any]:
        return self._get('/api/user-api-keys/status/')

    def save_provider_key(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('POST', '/api/user-api-keys/update/', payload=payload)

    def delete_provider_key(self, provider: str) -> Dict[str, Any]:
        return self._request('DELETE', f'/api/user-api-keys/{provider}/')

    def bot_usage(self, bot_id: int, params: Dict[str, Any]) -> Dict[str, Any]:
        """Per-bot usage for the bot's owner (DARE scopes rows to the caller)."""
        return self._get(f'/api/billing/bots/{bot_id}/usage/', params=params)
