"""
Shared X-Internal-Key validator for service-to-service endpoints.

Used by internal endpoints that DARE calls back into Socratic Bots (e.g.
``update_bot_budget``) to confirm the caller is the trusted DARE backend.
The same key is configured on both sides via ``DARE_INTERNAL_KEY`` env.

Usage::

    from utils.internal_auth import require_internal_key

    @api_view(['POST'])
    @require_internal_key
    def my_internal_endpoint(request):
        ...
"""
from functools import wraps

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response


def require_internal_key(view_func):
    """Reject requests missing or mismatching the X-Internal-Key header."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        provided = request.headers.get('X-Internal-Key', '')
        expected = getattr(settings, 'DARE_INTERNAL_KEY', '')
        if not expected or provided != expected:
            return Response(
                {'error': 'unauthorized', 'message': 'Invalid or missing X-Internal-Key'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return view_func(request, *args, **kwargs)

    return _wrapped
