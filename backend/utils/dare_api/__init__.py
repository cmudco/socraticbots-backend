"""
DARE API Client modules for Socratic Bots integration
"""

from .base import DareApiError, handle_dare_api_error
from .auth import DareAuthClient
from .files import DareFilesClient
from .health import DareHealthClient
from .models import DareModelsClient
from .notifications import DareNotificationsClient
from .wallets import DareWalletsClient
# from .conversations import DareConversationsClient  # Future implementation

# Create singleton instances
auth_client = DareAuthClient()
files_client = DareFilesClient()
health_client = DareHealthClient()
models_client = DareModelsClient()
notifications_client = DareNotificationsClient()


def get_wallets_client(token=None):
    """Factory: each request needs its own client bound to the caller's JWT."""
    return DareWalletsClient(token=token)
# conversations_client = DareConversationsClient()  # Future

__all__ = [
    'DareApiError',
    'handle_dare_api_error',
    'auth_client',
    'files_client',
    'health_client',
    'models_client',
    'notifications_client',
    'get_wallets_client',
    'DareWalletsClient',
    # 'conversations_client',
]