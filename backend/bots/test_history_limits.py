"""A bot's history windows default to the whole conversation and reach public chat."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Bot, BotGroup


class HistoryLimitAPITests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='history-owner@example.com', name='Owner', password='local-test',
            external_user_id=42,
        )
        self.owner._cached_role = 'CREATOR'
        self.group = BotGroup.objects.create(owner=self.owner, title='History QA')
        self.bot = Bot.objects.create(
            user=self.owner, bot_group=self.group, title='Tutor', subject='Science',
            topic='Energy', is_publicly_deployed=True, budget=10,
        )
        self.url = f'/api/bot-groups/{self.group.pk}/bots/{self.bot.pk}/'
        self.client.force_authenticate(self.owner)

    def test_new_bots_read_the_whole_conversation(self):
        body = self.client.get(self.url).json()
        self.assertEqual(body['chatHistoryLimit'], 0)
        self.assertEqual(body['trackingHistoryLimit'], 0)

    def test_windows_round_trip_to_public_chat(self):
        response = self.client.patch(
            self.url, {'chatHistoryLimit': 40, 'trackingHistoryLimit': 120}, format='json'
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(None)
        public = self.client.get(f'/api/conversations/public/bots/{self.bot.pk}/info/').json()
        self.assertEqual(public['chatHistoryLimit'], 40)
        self.assertEqual(public['trackingHistoryLimit'], 120)

    def test_negative_windows_are_rejected(self):
        response = self.client.patch(self.url, {'chatHistoryLimit': -1}, format='json')
        self.assertEqual(response.status_code, 400)
