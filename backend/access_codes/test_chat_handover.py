from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from access_codes.models import SubscriptionCodeAcceptance
from bots.models import Bot, BotGroup


class ChatHandoverAccessTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            email="handover-owner@example.test",
            name="Owner",
            password="test",
            external_user_id=81,
        )
        self.owner._cached_role = "CREATOR"
        self.student = User.objects.create_user(
            email="handover-student@example.test",
            name="Student",
            password="test",
            external_user_id=82,
        )
        self.student._cached_role = "SB_USER"
        self.other = User.objects.create_user(
            email="handover-other@example.test",
            name="Other",
            password="test",
            external_user_id=83,
        )
        self.other._cached_role = "SB_USER"
        self.group = BotGroup.objects.create(owner=self.owner, title="Handover")
        self.bot = Bot.objects.create(
            user=self.owner,
            bot_group=self.group,
            title="Tutor",
            subject="Science",
            topic="Energy",
        )
        self.generate = (
            f"/api/access-codes/bot-groups/{self.group.pk}/bots/{self.bot.pk}/generate/"
        )
        self.detail = f"/api/bot-groups/{self.group.pk}/bots/{self.bot.pk}/"

    @patch("access_codes.views.auth_client.sync_access_code_to_dare", return_value={})
    def test_generated_code_unlocks_bot_for_subscriber_and_enforces_limit(self, sync):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.generate, {"limit": 1}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        code = response.data["code"]
        self.assertTrue(code)
        sync.assert_called_once()
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(self.detail).status_code, 404)
        redeemed = self.client.post(
            "/api/access-codes/redeem/", {"accessCode": code}, format="json"
        )
        self.assertEqual(redeemed.status_code, 201, redeemed.data)
        self.assertEqual(self.client.get(self.detail).status_code, 200)
        self.assertEqual(
            SubscriptionCodeAcceptance.objects.filter(user=self.student).count(), 1
        )
        self.assertEqual(
            self.client.post(
                "/api/access-codes/redeem/", {"accessCode": code}, format="json"
            ).status_code,
            400,
        )
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.post(
                "/api/access-codes/redeem/", {"accessCode": code}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get(self.detail).status_code, 404)

    def test_subscriber_cannot_generate_or_change_bot_settings(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(
            self.client.post(self.generate, {"limit": 1}, format="json").status_code,
            403,
        )
        self.assertIn(
            self.client.patch(
                self.detail, {"ragMode": "agentic"}, format="json"
            ).status_code,
            [403, 404],
        )
