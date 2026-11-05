import secrets
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from access_codes.models import SubscriptionCode, SubscriptionCodeAcceptance
from bots.models import Bot, BotGroup
from utils.dare_api import DareApiError
from voice.access_codes import grant_voice_access
from voice.constants import VoiceAgentStatus, VoiceProvider
from voice.models import VoiceAgent, VoiceAgentAccess

User = get_user_model()

REGISTER_URL = '/api/access-codes/register/'
VOICE_CODE = 'VOICE-SIGNUP-1'
# Generated per run so no credential-looking literal lives in the repo.
TEST_PASSWORD = secrets.token_urlsafe(18)


def dare_check(exists=True, role='RESEARCHER', provisioned_by='SOCRATIC_VOICE', slots=9998):
    return {
        'exists': exists,
        'defaultRole': role if exists else None,
        'provisionedBy': provisioned_by if exists else None,
        'availableSlots': slots if exists else 0,
        'message': 'ok',
    }


def registration_payload(**overrides):
    payload = {
        'name': 'New Researcher',
        'email': 'new-researcher@example.com',
        'password': TEST_PASSWORD,
        'confirm_password': TEST_PASSWORD,
        'access_code': VOICE_CODE,
    }
    payload.update(overrides)
    return payload


class VoiceCodeRegistrationTests(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            email='creator@example.com', name='Creator', password='test-password'
        )
        self.reflection = VoiceAgent.objects.create(
            user=self.creator,
            name='Reflection',
            system_prompt='Ask reflective questions.',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code=VOICE_CODE,
            default_max_attempts=3,
        )
        self.exam = VoiceAgent.objects.create(
            user=self.creator,
            name='Oral exam',
            system_prompt='Examine the student.',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code=VOICE_CODE,
            default_max_attempts=1,
        )

        registration_client = patch('access_codes.serializers.auth_client')
        voice_client = patch('voice.access_codes.auth_client')
        self.dare = registration_client.start()
        self.voice_dare = voice_client.start()
        self.addCleanup(registration_client.stop)
        self.addCleanup(voice_client.stop)
        self.dare.check_access_code_exists.return_value = dare_check()
        self.dare.register_user.return_value = {'detail': 'Verification e-mail sent.'}
        self.voice_dare.provision_voice_access_code.return_value = {
            'success': True, 'created': True, 'isAvailable': True,
        }

    def register(self, **overrides):
        return self.client.post(REGISTER_URL, registration_payload(**overrides), format='json')

    def test_voice_code_signup_registers_researcher_and_unlocks_every_matching_assignment(self):
        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['user_type'], 'researcher')
        self.assertTrue(response.data['has_voice_access'])
        self.assertEqual(
            {item['id'] for item in response.data['voice_assignments']},
            {self.reflection.id, self.exam.id},
        )

        self.voice_dare.provision_voice_access_code.assert_called_once_with(VOICE_CODE, action='ensure')
        dare_payload = self.dare.register_user.call_args.args[0]
        self.assertEqual(dare_payload['access_code'], VOICE_CODE)
        self.assertNotIn('platform_role', dare_payload)

        user = User.objects.get(email='new-researcher@example.com')
        reflection_access = VoiceAgentAccess.objects.get(agent=self.reflection, user=user)
        exam_access = VoiceAgentAccess.objects.get(agent=self.exam, user=user)
        self.assertEqual(reflection_access.max_attempts, 3)
        self.assertEqual(exam_access.max_attempts, 1)
        self.assertFalse(SubscriptionCodeAcceptance.objects.filter(user=user).exists())

    def test_board_code_signup_still_works_without_touching_voice_provisioning(self):
        student = User.objects.create_user(
            email='prof@example.com', name='Prof', password='test-password'
        )
        group = BotGroup.objects.create(owner=student, title='Intro')
        bot = Bot.objects.create(
            bot_group=group, user=student, title='Tutor', subject='Math', topic='Algebra'
        )
        SubscriptionCode.objects.create(code='BOARD-1', bot=bot, created_by=student, limit=5)
        self.dare.check_access_code_exists.return_value = dare_check(
            role='SB_USER', provisioned_by='ADMIN'
        )

        response = self.register(access_code='BOARD-1', email='student@example.com')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['user_type'], 'user')
        self.assertTrue(response.data['has_bot_access'])
        self.assertFalse(response.data['has_voice_access'])
        self.assertEqual(response.data['voice_assignments'], [])
        self.voice_dare.provision_voice_access_code.assert_not_called()
        user = User.objects.get(email='student@example.com')
        self.assertTrue(
            SubscriptionCodeAcceptance.objects.filter(user=user, subscription_code__code='BOARD-1').exists()
        )
        self.assertFalse(VoiceAgentAccess.objects.filter(user=user).exists())

    def test_code_shared_by_a_bot_and_a_voice_assignment_is_refused(self):
        group = BotGroup.objects.create(owner=self.creator, title='Intro')
        bot = Bot.objects.create(
            bot_group=group, user=self.creator, title='Tutor', subject='Math', topic='Algebra'
        )
        SubscriptionCode.objects.create(code=VOICE_CODE, bot=bot, created_by=self.creator, limit=5)

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('both', str(response.data['access_code'][0]))
        self.dare.register_user.assert_not_called()
        self.voice_dare.provision_voice_access_code.assert_not_called()
        self.assertFalse(User.objects.filter(email='new-researcher@example.com').exists())

    def test_code_used_by_two_creators_is_refused(self):
        other = User.objects.create_user(
            email='other@example.com', name='Other', password='test-password'
        )
        VoiceAgent.objects.create(
            user=other,
            name='Other exam',
            system_prompt='x',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code=VOICE_CODE,
        )

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.dare.register_user.assert_not_called()
        self.voice_dare.provision_voice_access_code.assert_not_called()

    def test_unknown_code_is_still_invalid(self):
        self.dare.check_access_code_exists.return_value = dare_check(exists=False)

        response = self.register(access_code='NOPE')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid access code', str(response.data['access_code'][0]))
        self.dare.register_user.assert_not_called()

    def test_voice_code_whose_assignment_is_gone_is_refused_even_if_dare_still_has_it(self):
        VoiceAgent.objects.filter(access_code=VOICE_CODE).update(is_deleted=True, is_active=False)

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('no longer', str(response.data['access_code'][0]))
        self.dare.register_user.assert_not_called()
        self.voice_dare.provision_voice_access_code.assert_not_called()

    def test_dare_conflict_on_voice_code_is_refused(self):
        self.voice_dare.provision_voice_access_code.return_value = {
            'conflict': True, 'message': 'in use',
        }

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.dare.register_user.assert_not_called()
        self.assertFalse(User.objects.filter(email='new-researcher@example.com').exists())

    def test_dare_unreachable_while_provisioning_fails_closed(self):
        self.voice_dare.provision_voice_access_code.side_effect = DareApiError('boom')

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('unavailable', str(response.data['access_code'][0]).lower())
        self.dare.register_user.assert_not_called()

    def test_existing_email_is_refused_without_creating_anything(self):
        self.dare.register_user.side_effect = DareApiError(
            'A user with this email address already exists.', status_code=400
        )

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['detail'], 'A user with this email address already exists.'
        )
        self.assertFalse(User.objects.filter(email='new-researcher@example.com').exists())
        self.assertFalse(VoiceAgentAccess.objects.filter(user__email='new-researcher@example.com').exists())

    def test_retry_after_partial_local_failure_reuses_local_account(self):
        User.objects.create_user(
            email='new-researcher@example.com', name='Stale shell', password='x'
        )

        response = self.register()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(User.objects.filter(email='new-researcher@example.com').count(), 1)
        self.assertEqual(
            VoiceAgentAccess.objects.filter(user__email='new-researcher@example.com').count(), 2
        )

    def test_local_failure_after_dare_success_is_reported_honestly(self):
        with patch('access_codes.serializers.grant_voice_access', side_effect=RuntimeError('db')):
            response = self.register()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sign in', str(response.data).lower())
        self.assertFalse(VoiceAgentAccess.objects.filter(user__email='new-researcher@example.com').exists())

    def test_granting_access_is_idempotent_and_keeps_overrides(self):
        user = User.objects.create_user(email='s@example.com', name='S', password='x')

        first = grant_voice_access(user, [self.reflection, self.exam])
        VoiceAgentAccess.objects.filter(agent=self.exam, user=user).update(max_attempts=7)
        second = grant_voice_access(user, [self.reflection, self.exam])

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(VoiceAgentAccess.objects.filter(user=user).count(), 2)
        self.assertEqual(VoiceAgentAccess.objects.get(agent=self.exam, user=user).max_attempts, 7)
