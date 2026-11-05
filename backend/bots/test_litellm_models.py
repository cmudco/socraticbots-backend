"""Bots saved with a LiteLLM model: save-time checks and key lifecycle."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from utils.dare_api.models import BotModelCheckResult

from .models import Bot, BotGroup, BotModelPreference

KEY = "11111111-2222-3333-4444-555555555555"
OTHER_KEY = "99999999-2222-3333-4444-555555555555"
CHECK = "utils.dare_api.models_client.check_bot_models"
OK = BotModelCheckResult(chat_model_problem=None, tracking_model_problem=None)


class BotModelSaveCheckTests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="sponsor@example.com", name="Owner", password="local-test",
            external_user_id=41,
        )
        self.owner._cached_role = "CREATOR"
        self.group = BotGroup.objects.create(owner=self.owner, title="Gateway QA")
        self.bot = Bot.objects.create(
            user=self.owner, bot_group=self.group, title="Tutor", subject="Science",
            topic="Energy",
        )
        BotModelPreference.objects.create(
            bot=self.bot, chat_model_dare_id=f"litellm:{KEY}:gpt-5"
        )
        self.url = f"/api/bot-groups/{self.group.pk}/bots/{self.bot.pk}/"
        self.client.force_authenticate(self.owner)

    @patch(CHECK, return_value=OK)
    def test_owner_can_save_a_model_dare_accepts(self, check):
        response = self.client.patch(
            self.url, {"chatModelDareId": f"litellm:{KEY}:claude-opus-5"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        check.assert_called_once_with(41, f"litellm:{KEY}:claude-opus-5", None)
        self.assertEqual(
            BotModelPreference.objects.get(bot=self.bot).chat_model_dare_id,
            f"litellm:{KEY}:claude-opus-5",
        )

    @patch(
        CHECK,
        return_value=BotModelCheckResult(
            chat_model_problem="KEY_UNAVAILABLE", tracking_model_problem=None
        ),
    )
    def test_a_model_dare_rejects_is_not_saved(self, _check):
        response = self.client.patch(
            self.url, {"chatModelDareId": f"litellm:{OTHER_KEY}:gpt-5"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("LiteLLM key", response.json()["chatModelDareId"][0])
        self.assertEqual(
            BotModelPreference.objects.get(bot=self.bot).chat_model_dare_id,
            f"litellm:{KEY}:gpt-5",
        )

    @patch(CHECK)
    def test_unrelated_edits_do_not_recheck_the_saved_model(self, check):
        response = self.client.patch(
            self.url,
            {"topic": "Heat", "chatModelDareId": f"litellm:{KEY}:gpt-5"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        check.assert_not_called()


@override_settings(DARE_INTERNAL_KEY="shared-internal-key")
class LiteLLMKeyLifecycleTests(APITestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(
            email="owner@example.com", name="Owner", password="x", external_user_id=42,
        )
        group = BotGroup.objects.create(owner=owner, title="Gateway")
        self.sponsored = Bot.objects.create(
            bot_group=group, user=owner, title="Sponsored", subject="S", topic="T",
        )
        self.other = Bot.objects.create(
            bot_group=group, user=owner, title="Other key", subject="S", topic="T",
        )
        BotModelPreference.objects.create(
            bot=self.sponsored, chat_model_dare_id=f"litellm:{KEY}:gpt-5",
            tracking_model_dare_id="7",
        )
        BotModelPreference.objects.create(
            bot=self.other, chat_model_dare_id=f"litellm:{OTHER_KEY}:gpt-5",
        )
        self.headers = {"HTTP_X_INTERNAL_KEY": "shared-internal-key"}

    def test_dependents_list_only_bots_routed_through_the_key(self):
        response = self.client.get(
            f"/api/bots/internal/litellm-key-dependents/{KEY}/", **self.headers
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bots = response.json()["dependentBots"]
        self.assertEqual([bot["botId"] for bot in bots], [self.sponsored.pk])
        self.assertEqual(bots[0]["usageType"], "chat")

    def test_clearing_a_key_leaves_other_keys_and_dare_models_alone(self):
        response = self.client.post(
            f"/api/bots/internal/nullify-litellm-key/{KEY}/", **self.headers
        )

        self.assertEqual(response.json()["affectedBotsCount"], 1)
        sponsored = BotModelPreference.objects.get(bot=self.sponsored)
        self.assertIsNone(sponsored.chat_model_dare_id)
        self.assertEqual(sponsored.tracking_model_dare_id, "7")
        self.assertFalse(Bot.objects.get(pk=self.sponsored.pk).is_active)
        self.assertEqual(
            BotModelPreference.objects.get(bot=self.other).chat_model_dare_id,
            f"litellm:{OTHER_KEY}:gpt-5",
        )
        self.assertTrue(Bot.objects.get(pk=self.other.pk).is_active)

    def test_internal_key_is_required(self):
        response = self.client.get(f"/api/bots/internal/litellm-key-dependents/{KEY}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
