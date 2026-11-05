"""
Authentication utilities for SocraticBots backend.
"""


def get_bearer_token(request) -> str | None:
    """
    Extract Bearer token from request Authorization header.

    Args:
        request: Django/DRF request object

    Returns:
        The token string if present, None otherwise
    """
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ')[1]
    return None
