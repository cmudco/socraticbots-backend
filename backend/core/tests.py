"""
Tests for the health and readiness endpoints.
"""

from unittest.mock import patch

from django.test import TestCase

from utils.dare_api import DareApiError


class HealthEndpointTests(TestCase):
    def test_health_answers_without_auth(self) -> None:
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    @patch("core.views.health_client.check_health")
    def test_ready_when_database_and_dare_are_up(self, check_health) -> None:
        response = self.client.get("/api/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["checks"], {"database": "ok", "dare": "ok"})

    @patch("core.views.health_client.check_health")
    def test_not_ready_when_dare_is_down(self, check_health) -> None:
        check_health.side_effect = DareApiError("DARE health check failed: ConnectionError")
        response = self.client.get("/api/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
