"""The bot's retrieval selection must survive the camelCase API and storage."""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Bot, BotGroup


class RetrievalModeAPITests(APITestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email='retrieval-owner@example.com', name='Owner', password='local-test',
            external_user_id=41,
        )
        self.owner._cached_role = 'CREATOR'
        self.group = BotGroup.objects.create(owner=self.owner, title='Retrieval QA')
        self.bot = Bot.objects.create(
            user=self.owner, bot_group=self.group, title='Tutor', subject='Science',
            topic='Energy', is_publicly_deployed=True, budget=10,
        )
        self.url = f'/api/bot-groups/{self.group.pk}/bots/{self.bot.pk}/'
        self.client.force_authenticate(self.owner)

    def test_all_modes_round_trip_through_api_database_and_public_info(self):
        for mode in ('naive', 'advanced', 'agentic'):
            with self.subTest(mode=mode):
                response = self.client.patch(self.url, {'ragMode': mode}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.json()['ragMode'], mode)
                self.bot.refresh_from_db()
                self.assertEqual(self.bot.rag_mode, mode)
                self.assertEqual(self.client.get(self.url).json()['ragMode'], mode)
                self.client.force_authenticate(None)
                public = self.client.get(f'/api/conversations/public/bots/{self.bot.pk}/info/')
                self.assertEqual(public.status_code, 200, public.data)
                self.assertEqual(public.json()['ragMode'], mode)
                self.client.force_authenticate(self.owner)

    def test_default_is_advanced_and_teaching_mode_is_independent(self):
        self.assertEqual(self.bot.rag_mode, 'advanced')
        response = self.client.patch(self.url, {'isAdvanced': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.bot.refresh_from_db()
        self.assertTrue(self.bot.is_advanced)
        self.assertEqual(self.bot.rag_mode, 'advanced')

    def test_invalid_mode_rejected_without_changing_saved_selection(self):
        response = self.client.patch(self.url, {'ragMode': 'invalid'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.rag_mode, 'advanced')

    def test_unauthenticated_and_unrelated_user_cannot_change_mode(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.patch(self.url, {'ragMode': 'agentic'}, format='json').status_code, 401)
        other = get_user_model().objects.create_user(email='other@example.com', name='Other')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.patch(self.url, {'ragMode': 'agentic'}, format='json').status_code, 404)
        self.bot.refresh_from_db()
        self.assertEqual(self.bot.rag_mode, 'advanced')

    def test_create_accepts_each_mode(self):
        for mode in ('naive', 'advanced', 'agentic'):
            response = self.client.post(f'/api/bot-groups/{self.group.pk}/bots/', {
                'title': mode, 'subject': 'Science', 'topic': 'Energy', 'ragMode': mode,
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(Bot.objects.get(pk=response.json()['id']).rag_mode, mode)
