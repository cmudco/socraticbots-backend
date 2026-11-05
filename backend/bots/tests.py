from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Bot, BotGroup, BotModelPreference


@override_settings(DARE_INTERNAL_KEY="shared-internal-key")
class ModelDependencyEndpointTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            email="owner@example.com",
            name="Owner",
            password="test-password",
            external_user_id=42,
        )
        self.group = BotGroup.objects.create(owner=self.owner, title="Biology")
        self.chat_bot = Bot.objects.create(
            bot_group=self.group,
            user=self.owner,
            title="Cell tutor",
            subject="Biology",
            topic="Cells",
        )
        self.tracking_bot = Bot.objects.create(
            bot_group=self.group,
            user=self.owner,
            title="Progress tracker",
            subject="Biology",
            topic="Progress",
        )
        BotModelPreference.objects.create(
            bot=self.chat_bot,
            chat_model_dare_id="7",
            tracking_model_dare_id="7",
        )
        BotModelPreference.objects.create(
            bot=self.tracking_bot,
            chat_model_dare_id="99",
            tracking_model_dare_id="7",
        )
        self.preview_url = "/api/bots/internal/model-dependents/7/"
        self.nullify_url = "/api/bots/internal/nullify-model/7/"
        self.headers = {"HTTP_X_INTERNAL_KEY": "shared-internal-key"}

    def test_internal_key_is_required(self):
        preview_response = self.client.get(self.preview_url)
        nullify_response = self.client.post(self.nullify_url)

        self.assertEqual(preview_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(nullify_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_preview_returns_each_affected_bot_once_with_owner_and_route_ids(self):
        response = self.client.get(self.preview_url, **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["dependentBotsCount"], 2)
        bots = {bot["botId"]: bot for bot in payload["dependentBots"]}
        self.assertEqual(bots[self.chat_bot.pk]["usageType"], "chat and tracking")
        self.assertEqual(bots[self.chat_bot.pk]["botGroupId"], self.group.pk)
        self.assertEqual(bots[self.chat_bot.pk]["ownerDareId"], 42)
        self.assertEqual(bots[self.chat_bot.pk]["ownerEmail"], "owner@example.com")

    def test_nullify_is_idempotent_and_preserves_other_models(self):
        response = self.client.post(self.nullify_url, **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["affectedBotsCount"], 2)
        self.assertEqual(response.json()["affectedOwnerDareIds"], [42])

        chat_preference = BotModelPreference.objects.get(bot=self.chat_bot)
        tracking_preference = BotModelPreference.objects.get(bot=self.tracking_bot)
        self.assertIsNone(chat_preference.chat_model_dare_id)
        self.assertIsNone(chat_preference.tracking_model_dare_id)
        self.assertEqual(tracking_preference.chat_model_dare_id, "99")
        self.assertIsNone(tracking_preference.tracking_model_dare_id)
        self.assertFalse(Bot.objects.get(pk=self.chat_bot.pk).is_active)
        self.assertFalse(Bot.objects.get(pk=self.tracking_bot.pk).is_active)

        second_response = self.client.post(self.nullify_url, **self.headers)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.json()["affectedBotsCount"], 0)
