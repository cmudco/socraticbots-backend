from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from utils.dare_api.notifications import DareNotificationsClient


@override_settings(
    DARE_BACKEND_URL="https://dare.example",
    SOCRATIC_BOTS_BACKEND_URL="https://socratic.example",
)
class NotificationProxyClientTests(SimpleTestCase):
    @patch("utils.dare_api.notifications.requests.get")
    def test_notification_history_flag_is_forwarded_to_dare(self, request_get):
        response = Mock(status_code=200)
        response.json.return_value = {"count": 0, "results": []}
        request_get.return_value = response
        client = DareNotificationsClient()

        client.get_notifications(
            user_token="test-token",
            include_read=True,
        )

        request_get.assert_called_once_with(
            "https://dare.example/api/notifications/",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://socratic.example",
                "Referer": "https://socratic.example",
                "Authorization": "Bearer test-token",
            },
            params={"exclude_expired": "true", "include_read": "true"},
            timeout=30,
        )
