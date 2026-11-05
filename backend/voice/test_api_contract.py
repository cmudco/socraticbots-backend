"""Assert rendered HTTP JSON, not the serializer's pre-rendered data."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from voice.constants import ConversationStatus, VoiceAgentStatus, VoiceProvider
from voice.models import VoiceAgent, VoiceAgentAccess, VoiceConversation


CONTRACT = json.loads((Path(__file__).parent / 'fixtures/api_contract.json').read_text())
START = datetime(2026, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 20, 0, 0, 10, tzinfo=timezone.utc)


@override_settings(
    VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED=True,
    VOICE_RUNTIME_PUBLIC_URL='http://runtime.test',
    VOICE_RUNTIME_SESSION_SECRET='contract-secret',
    DARE_INTERNAL_KEY='contract-key',
)
class VoiceApiContractTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(pk=1, email='owner@example.test', name='Owner')
        self.student = users.objects.create_user(pk=2, email='student@example.test', name='Student')
        self.agent = VoiceAgent.objects.create(
            pk=37, user=self.owner, name='Contract exam', system_prompt='Test',
            first_message='Hello', voice_provider=VoiceProvider.MISTRAL_VOICE,
            status=VoiceAgentStatus.ACTIVE,
        )
        VoiceAgentAccess.objects.create(agent=self.agent, user=self.student, max_attempts=1)
        self.client.force_authenticate(self.student)
        self.base = '/api/voice/agents/37/'

    def conversation(self, status=ConversationStatus.RESERVED):
        conversation = VoiceConversation.objects.create(
            pk=91, agent=self.agent, user=self.student, status=status,
            elevenlabs_conversation_id='contract-session',
            provider_conversation_id='contract-session',
        )
        VoiceConversation.objects.filter(pk=91).update(started_at=START, created_at=START)
        return conversation

    def body(self, response, status=200):
        self.assertEqual(response.status_code, status, response.content)
        self.assertTrue(response['Content-Type'].startswith('application/json'))
        return json.loads(response.content)

    def test_signed_url_response_is_camel_case(self):
        body = self.body(self.client.post(self.base + 'get_signed_url/'))
        self.assertEqual(set(body), {
            'provider', 'sessionId', 'webrtcUrl', 'iceServers', 'token', 'expiresAt',
        })
        self.assertEqual(body['provider'], 'mistral_pipecat')
        self.assertIsInstance(body['sessionId'], str)
        self.assertTrue(body['token'])
        self.assertIsInstance(body['iceServers'], list)
        self.assertTrue(body['webrtcUrl'].startswith('http://runtime.test/'))
        datetime.fromisoformat(body['expiresAt'])

    def test_status_explicitly_returns_null_before_an_ending(self):
        self.conversation()
        response = self.client.get(self.base + 'session_status/', {
            'conversation_id': 'contract-session',
        })
        self.assertEqual(self.body(response), CONTRACT['statusReserved'])

    def test_callback_to_history_detail_and_status_matches_frontend_fixture(self):
        self.conversation()
        with patch('voice.services.session_service.timezone.now', return_value=END):
            callback = self.client.post('/api/voice/runtime/conversation-ended/', {
                'sessionId': 'contract-session', 'status': 'cancelled',
                'endedReason': 'page_hidden_exit', 'durationSeconds': 10,
                'transcript': CONTRACT['detail']['transcript'],
                'metrics': {'sessionHealth': {'activity': 'conversation'}},
            }, format='json', HTTP_X_INTERNAL_KEY='contract-key')
        self.body(callback)
        self.assertEqual(self.body(self.client.get('/api/voice/conversations/91/')), CONTRACT['detail'])
        self.assertEqual(self.body(self.client.get('/api/voice/conversations/', {
            'agent_id': 37,
        })), CONTRACT['list'])
        self.assertEqual(self.body(self.client.get(self.base + 'session_status/', {
            'conversation_id': 'contract-session',
        })), CONTRACT['statusCancelled'])

    def test_camel_case_cancel_request_and_legacy_null_metadata(self):
        self.conversation()
        with patch('voice.services.session_service.timezone.now', return_value=END):
            body = self.body(self.client.post(self.base + 'cancel_conversation/', {
                'conversationId': 'contract-session', 'endedReason': 'startup_cancelled',
            }, format='json'))
        self.assertEqual(body['status'], 'cancelled')
        self.assertEqual(body['endedReason'], 'startup_cancelled')
        self.assertIsNone(body['sessionActivity'])
        self.assertEqual(body['transcript'], [])
        self.assertNotIn('ended_reason', body)

    def test_null_metadata_on_older_conversation(self):
        self.conversation()
        body = self.body(self.client.get('/api/voice/conversations/91/'))
        for key in ('endedReason', 'sessionActivity', 'endedAt', 'durationSeconds'):
            self.assertIsNone(body[key])
        self.assertEqual(body['transcript'], [])

    def test_status_and_error_codes_are_distinct_http_contracts(self):
        conversation = self.conversation(ConversationStatus.IN_PROGRESS)
        # Freeze the clock near START so the stale-attempt sweep keeps the session active.
        with patch('voice.services.session_service.timezone.now', return_value=END):
            body = self.body(self.client.post(self.base + 'get_signed_url/'), 409)
        self.assertEqual(body['code'], 'session_active')
        self.assertIsInstance(body['error'], str)
        conversation.status = ConversationStatus.COMPLETED
        conversation.compliance_receipt = {'endedReason': 'manual_end'}
        conversation.save()
        self.assertEqual(self.body(self.client.get(self.base + 'session_status/', {
            'conversation_id': 'contract-session',
        })), CONTRACT['statusCompleted'])
        body = self.body(self.client.post(self.base + 'get_signed_url/'), 403)
        self.assertEqual(body['code'], 'attempt_limit_reached')

    def test_internal_context_deliberately_keeps_snake_case(self):
        self.conversation()
        body = self.body(self.client.post(
            '/api/voice/runtime/sessions/contract-session/context/',
            HTTP_X_INTERNAL_KEY='contract-key',
        ))
        self.assertEqual(body['first_message'], 'Hello')
        self.assertIn('system_prompt', body)
        self.assertNotIn('firstMessage', body)
