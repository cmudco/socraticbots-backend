"""Local-only regression tests for reservation ownership and late callbacks."""
from datetime import timedelta
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APITestCase

from voice.api.serializers import VoiceConversationListSerializer, VoiceConversationSerializer
from voice.constants import ConversationStatus, VoiceAgentStatus, VoiceProvider
from voice.dtos import MistralConversationEndedPayload
from voice.models import VoiceAgent, VoiceAgentAccess, VoiceConversation
from voice.services.session_service import VoiceSessionService, VoiceSessionError


@override_settings(VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED=True,
                   VOICE_RUNTIME_PUBLIC_URL='http://runtime.test',
                   VOICE_RUNTIME_SESSION_SECRET='test-secret', DARE_INTERNAL_KEY='test-key')
class SessionLifecycleTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email='voice-owner@example.com', name='Owner', password='test')
        self.student = User.objects.create_user(email='voice-student@example.com', name='Student', password='test')
        self.agent = VoiceAgent.objects.create(user=self.owner, name='Test', system_prompt='Test',
            status=VoiceAgentStatus.ACTIVE, voice_provider=VoiceProvider.MISTRAL_VOICE)
        VoiceAgentAccess.objects.create(agent=self.agent, user=self.student, max_attempts=1)
        self.service = VoiceSessionService()

    def reserve(self):
        session = self.service.start_session(self.agent, self.student)
        return VoiceConversation.objects.get(provider_conversation_id=session.session_id)

    def test_late_navigation_enriches_unknown_disconnect_without_changing_outcome(self):
        conversation = self.reserve()
        ended_at = timezone.now()
        conversation.status = ConversationStatus.CANCELLED
        conversation.ended_at = ended_at
        conversation.duration_seconds = 4
        conversation.transcript = [{'role': 'agent', 'message': 'Hello'}]
        conversation.compliance_receipt = {'endedReason': 'unknown_disconnect', 'metrics': {'kept': True}}
        conversation.save()
        self.client.force_authenticate(self.student)
        response = self.client.post(f'/api/voice/agents/{self.agent.pk}/cancel_conversation/', {
            'conversationId': conversation.provider_conversation_id, 'endedReason': 'route_change',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['endedReason'], 'route_change')
        self.assertEqual(body['status'], 'cancelled')
        conversation.refresh_from_db()
        self.assertEqual(conversation.ended_at, ended_at)
        self.assertEqual(conversation.duration_seconds, 4)
        self.assertEqual(conversation.transcript, [{'role': 'agent', 'message': 'Hello'}])
        self.assertEqual(conversation.compliance_receipt['runtimeEndedReason'], 'unknown_disconnect')
        self.assertEqual(conversation.compliance_receipt['metrics'], {'kept': True})

    def test_navigation_never_rewrites_completed_known_or_old_outcomes(self):
        conversation = self.reserve()
        for status, reason, age in [
            (ConversationStatus.COMPLETED, 'manual_end', 0),
            (ConversationStatus.CANCELLED, 'page_hidden_exit', 0),
            (ConversationStatus.CANCELLED, 'unknown_disconnect', 120),
        ]:
            with self.subTest(status=status, reason=reason, age=age):
                conversation.status = status
                conversation.ended_at = timezone.now() - timedelta(seconds=age)
                conversation.compliance_receipt = {'endedReason': reason}
                conversation.save()
                self.service.cancel_conversation(self.agent, self.student, conversation.provider_conversation_id, 'route_change')
                conversation.refresh_from_db()
                self.assertEqual(conversation.status, status)
                self.assertEqual(conversation.compliance_receipt['endedReason'], reason)

    def test_runtime_health_survives_callback_case_conversion(self):
        conversation = self.reserve()
        response = self.client.post('/api/voice/runtime/conversation-ended/', {
            'sessionId': conversation.provider_conversation_id,
            'status': 'cancelled',
            'endedReason': 'page_hidden_exit',
            'metrics': {'sessionHealth': {'activity': 'conversation'}},
        }, format='json', HTTP_X_INTERNAL_KEY='test-key')
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        for serializer in (VoiceConversationListSerializer, VoiceConversationSerializer):
            data = serializer(conversation).data
            self.assertEqual(data['session_activity'], 'conversation')
            self.assertEqual(data['ended_reason'], 'page_hidden_exit')

    def claim(self, conversation):
        return self.client.post(f'/api/voice/runtime/sessions/{conversation.provider_conversation_id}/context/',
                                HTTP_X_INTERNAL_KEY='test-key')

    def test_retry_releases_only_unclaimed_reservation(self):
        first = self.reserve()
        second = self.reserve()
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.CANCELLED)
        self.assertEqual(first.compliance_receipt['endedReason'], 'startup_replaced')
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(self.claim(first).status_code, 409)
        self.assertFalse(self.service.start_mistral_conversation(first.provider_conversation_id))

    def test_claim_blocks_duplicate_offer_and_retry_until_expiry(self):
        first = self.reserve()
        self.assertEqual(self.claim(first).status_code, 200)
        self.assertEqual(self.claim(first).status_code, 409)
        with self.assertRaises(VoiceSessionError) as caught:
            self.reserve()
        self.assertEqual(caught.exception.code, 'session_starting')
        first.refresh_from_db()
        first.compliance_receipt['runtimeClaimedAt'] = (timezone.now() - timedelta(seconds=100)).isoformat()
        first.save(update_fields=['compliance_receipt'])
        self.assertFalse(self.service.start_mistral_conversation(first.provider_conversation_id))
        self.reserve()
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.CANCELLED)

    def test_active_call_is_not_reclaimed_or_cancelled_by_late_start_failure(self):
        first = self.reserve()
        self.claim(first)
        self.assertTrue(self.service.start_mistral_conversation(first.provider_conversation_id))
        self.service.cancel_conversation(self.agent, self.student, first.provider_conversation_id, 'start_failed')
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.IN_PROGRESS)
        with self.assertRaises(VoiceSessionError) as caught:
            self.reserve()
        self.assertEqual(caught.exception.code, 'session_active')

    def test_cancelled_start_cannot_be_revived_by_late_completion(self):
        first = self.reserve()
        self.reserve()
        self.service.complete_mistral_conversation(MistralConversationEndedPayload(
            session_id=first.provider_conversation_id, status='completed', ended_reason='manual_end'))
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.CANCELLED)

    @patch('voice.services.session_service.WebhookService')
    def test_duplicate_terminal_callback_does_not_overwrite_or_upload_twice(self, webhook):
        first = self.reserve()
        self.claim(first)
        self.service.start_mistral_conversation(first.provider_conversation_id)
        payload = MistralConversationEndedPayload(session_id=first.provider_conversation_id,
                                                  status='completed', ended_reason='manual_end')
        with self.captureOnCommitCallbacks(execute=True):
            self.service.complete_mistral_conversation(payload)
            self.service.complete_mistral_conversation(payload)
            self.service.complete_mistral_conversation(MistralConversationEndedPayload(
                session_id=first.provider_conversation_id, status='cancelled', ended_reason='unknown_disconnect'))
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.COMPLETED)
        webhook.return_value.upload_transcript_to_dare.assert_called_once()
        with self.assertRaises(VoiceSessionError) as caught:
            self.reserve()
        self.assertEqual(caught.exception.code, 'attempt_limit_reached')

    @override_settings(VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED=False)
    def test_mixed_version_rollout_does_not_replace_unclaimed_start(self):
        first = self.reserve()
        with self.assertRaises(VoiceSessionError):
            self.reserve()
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.RESERVED)

    def test_claim_requires_internal_authentication(self):
        first = self.reserve()
        response = self.client.post(f'/api/voice/runtime/sessions/{first.provider_conversation_id}/context/')
        self.assertEqual(response.status_code, 401)

    def test_background_expiry_does_not_need_a_student_retry(self):
        first = self.reserve()
        VoiceConversation.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(seconds=100))
        call_command('expire_voice_startups')
        first.refresh_from_db()
        self.assertEqual(first.status, ConversationStatus.CANCELLED)
        self.assertEqual(first.compliance_receipt['endedReason'], 'reserved_session_expired')

    def test_status_endpoint_is_scoped_to_the_student(self):
        first = self.reserve()
        self.client.force_authenticate(self.student)
        url = f'/api/voice/agents/{self.agent.id}/session_status/?conversation_id={first.provider_conversation_id}'
        self.assertEqual(self.client.get(url).data['status'], ConversationStatus.RESERVED)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(url).status_code, 404)
