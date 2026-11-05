"""Rendered API contract and ownership checks for browser evidence."""
import json
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from voice.constants import ConversationStatus
from voice.models import VoiceAgent, VoiceAgentAccess, VoiceBrowserDiagnostic, VoiceConversation


CONTRACT = json.loads((Path(__file__).parent / 'fixtures/api_contract.json').read_text())


class BrowserDiagnosticsTests(APITestCase):
    def setUp(self):
        cache.clear()
        users = get_user_model()
        self.owner = users.objects.create_user(email='owner@example.test', name='Owner')
        self.student = users.objects.create_user(email='student@example.test', name='Student')
        self.agent = VoiceAgent.objects.create(user=self.owner, name='Exam')
        VoiceAgentAccess.objects.create(agent=self.agent, user=self.student)
        self.client.force_authenticate(self.student)
        self.url = f'/api/voice/agents/{self.agent.pk}/browser_diagnostics/'
        self.payload = {'attemptId': str(uuid4()), 'events': [CONTRACT['browserEvent']]}

    def post(self, payload=None, expected=204):
        response = self.client.post(self.url, payload or self.payload, format='json')
        self.assertEqual(response.status_code, expected, response.content)
        return response

    def conversation(self, user=None):
        return VoiceConversation.objects.create(
            agent=self.agent, user=user or self.student,
            elevenlabs_conversation_id=str(uuid4()), provider_conversation_id=str(uuid4()),
            status=ConversationStatus.CANCELLED,
            compliance_receipt={'endedReason': 'unknown_disconnect'},
        )

    def test_permission_failure_is_saved_without_consuming_an_attempt(self):
        self.post()
        diagnostic = VoiceBrowserDiagnostic.objects.get()
        self.assertIsNone(diagnostic.conversation_id)
        self.assertEqual(diagnostic.events[0]['error_name'], 'NotAllowedError')
        self.assertEqual(diagnostic.events[0]['elapsed_ms'], 1200)
        self.assertFalse(VoiceConversation.objects.exists())

    def test_late_link_and_duplicate_upload_preserve_outcome_and_render_camel_case(self):
        self.post()
        conversation = self.conversation()
        self.payload['conversationId'] = conversation.provider_conversation_id
        self.post()
        self.post()
        response = self.client.get(f'/api/voice/conversations/{conversation.pk}/')
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body['browserDiagnostics'], [CONTRACT['browserEvent']])
        self.assertEqual(body['endedReason'], 'unknown_disconnect')
        self.assertEqual(body['status'], 'cancelled')
        response = self.client.get('/api/voice/conversations/', {'agent_id': self.agent.pk})
        self.assertEqual(json.loads(response.content)[0]['browserDiagnostics'], [CONTRACT['browserEvent']])

    def test_older_batches_do_not_erase_later_evidence(self):
        self.post({**self.payload, 'events': [{**CONTRACT['browserEvent'], 'sequence': 2}]})
        self.post()
        self.assertEqual([e['sequence'] for e in VoiceBrowserDiagnostic.objects.get().events], [0, 2])

    def test_cannot_report_for_another_user_or_relink_a_conversation(self):
        other = self.conversation(self.owner)
        self.post({**self.payload, 'conversationId': other.provider_conversation_id}, expected=403)
        own = self.conversation()
        self.post({**self.payload, 'conversationId': own.provider_conversation_id})
        self.post({**self.payload, 'attemptId': str(uuid4()), 'conversationId': own.provider_conversation_id}, expected=400)
        self.client.force_authenticate(self.owner)
        self.post(expected=403)

    def test_requires_agent_access_and_authentication(self):
        stranger = get_user_model().objects.create_user(email='stranger@example.test', name='Stranger')
        self.client.force_authenticate(stranger)
        self.post(expected=403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.post(self.url, self.payload, format='json').status_code, [401, 403])
        self.assertFalse(VoiceBrowserDiagnostic.objects.exists())

    def test_payload_is_bounded_and_does_not_store_arbitrary_text(self):
        self.post({**self.payload, 'events': [CONTRACT['browserEvent']] * 65}, expected=400)
        self.post({**self.payload, 'events': [{**CONTRACT['browserEvent'], 'errorName': 'secret text'}]}, expected=400)
        self.post({**self.payload, 'events': [{**CONTRACT['browserEvent'], 'message': 'private transcript'}]})
        self.assertNotIn('message', VoiceBrowserDiagnostic.objects.get().events[0])

    def test_admin_displays_microphone_evidence_without_a_conversation(self):
        self.post()
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        self.client.force_login(self.owner)
        response = self.client.get(f'/admin/voice/voicebrowserdiagnostic/{self.payload["attemptId"]}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NotAllowedError')
        self.assertContains(response, 'Browser-reported signals')
