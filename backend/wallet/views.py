"""
Socratic Bots → DARE wallet pass-through endpoints.

Each view forwards the caller's JWT to the corresponding DARE billing endpoint
and returns the response body verbatim. Per ``sb-dare-integration``:
- Never re-camelize. DRF on the DARE side already emits camelCase.
- All DARE traffic goes through ``utils.dare_api/``; never call ``requests``
  here directly.

Why a thin SB-side proxy at all (instead of having SB-react call DARE)?
- Browsers in Socratic Bots already hold a DARE-issued JWT; routing through SB
  keeps the network-allowed origin list short (one backend) and lets us add
  SB-only filtering later (e.g. a per-bot usage call needing SB context) without
  changing the FE contract.
- Keeps DARE's wallet endpoints loosely coupled — a future change in DARE
  (say, a different transactions response shape) is absorbed by this module
  rather than touching the React app.
"""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from users.authentication import JWTAuthentication
from utils.dare_api import DareApiError, get_wallets_client

logger = logging.getLogger(__name__)


def _client_for(request):
    """Build a wallet client bound to the caller's bearer token."""
    auth_header = request.headers.get('Authorization', '')
    token = auth_header.split(' ', 1)[1] if auth_header.startswith('Bearer ') else None
    return get_wallets_client(token=token)


def _proxy(method_name, request, *args, **kwargs):
    """Generic proxy helper — call ``method_name(*args, **kwargs)`` on the
    wallet client and translate ``DareApiError`` to the same HTTP status."""
    client = _client_for(request)
    try:
        body = getattr(client, method_name)(*args, **kwargs)
    except DareApiError as exc:
        return Response(
            {'detail': exc.message, **(exc.details or {})},
            status=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        )
    if not body and request.method == 'DELETE':
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(body)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def wallet_list(request):
    """Active wallet + the list of wallets visible to the caller."""
    return _proxy('list_wallets', request)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def wallet_transactions(request):
    """Caller's transactions, defaulted to the Socratic Bots platform.

    Honors ``platform`` / ``billing_mode`` query params if the caller
    explicitly asks for cross-platform results.
    """
    platform = request.query_params.get('platform', 'SocraticBots')
    billing_mode = request.query_params.get('billing_mode')
    return _proxy(
        'list_transactions',
        request,
        platform=platform,
        billing_mode=billing_mode,
    )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def wallet_effective_policy(request):
    """Resolved refill amount / period (USER → GROUP → SYSTEM)."""
    return _proxy('effective_policy', request)


def _wallet_view(methods):
    """Authenticated function view that forwards the caller's DARE JWT."""
    def decorate(func):
        func = permission_classes([IsAuthenticated])(func)
        func = authentication_classes([JWTAuthentication])(func)
        return api_view(methods)(func)
    return decorate


# ============================================================================
# Wallet management — mirrors DARE's own wallet popover
# ============================================================================


@_wallet_view(['PUT'])
def wallet_set_active(request):
    """Switch the caller's default wallet (``{type, refId}``)."""
    return _proxy('set_active_wallet', request, request.data)


@_wallet_view(['POST'])
def litellm_key_create(request):
    """Save a LiteLLM key the caller has already tested."""
    return _proxy('create_litellm_key', request, request.data)


@_wallet_view(['PATCH', 'DELETE'])
def litellm_key_detail(request, key_id):
    """Rename or remove one of the caller's LiteLLM keys."""
    if request.method == 'DELETE':
        return _proxy('delete_litellm_key', request, str(key_id))
    return _proxy('update_litellm_key', request, str(key_id), request.data)


@_wallet_view(['POST'])
def litellm_key_test_unsaved(request):
    """Probe a gateway URL + key before saving it."""
    return _proxy('test_unsaved_litellm_key', request, request.data)


@_wallet_view(['POST'])
def litellm_key_test_saved(request, key_id):
    """Probe a saved LiteLLM key's gateway."""
    return _proxy('test_saved_litellm_key', request, str(key_id))


@_wallet_view(['GET'])
def litellm_key_dependents(request, key_id):
    """Bots that stop answering if this key is deleted."""
    return _proxy('litellm_key_dependents', request, str(key_id))


@_wallet_view(['GET'])
def provider_key_status(request):
    """Which providers the caller has a BYO key for."""
    return _proxy('provider_key_status', request)


@_wallet_view(['POST'])
def provider_key_save(request):
    """Set the caller's BYO key for one provider."""
    return _proxy('save_provider_key', request, request.data)


@_wallet_view(['DELETE'])
def provider_key_delete(request, provider):
    """Clear the caller's BYO key for one provider."""
    return _proxy('delete_provider_key', request, provider)


@_wallet_view(['GET'])
def bot_usage(request, bot_id):
    """What a bot has cost: chatters' DARE spend and the owner's sponsored spend."""
    params = {
        name: request.query_params[name]
        for name in ('period', 'group_by')
        if name in request.query_params
    }
    return _proxy('bot_usage', request, bot_id, params)
