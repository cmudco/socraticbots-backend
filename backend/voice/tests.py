from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from voice.api.serializers import VoiceAgentUpdateSerializer
from voice.constants import ConversationStatus, VoiceAgentStatus, VoiceProvider
from voice.models import VoiceAgent, VoiceAgentAccess, VoiceConversation


class VoiceAgentApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            email='owner@example.com',
            name='Owner',
            password='test-password',
        )
        self.student = User.objects.create_user(
            email='student@example.com',
            name='Student',
            password='test-password',
        )
        self.creator = User.objects.create_user(
            email='creator@example.com',
            name='Creator',
            password='test-password',
        )
        self.creator._cached_role = 'CREATOR'
        self.researcher = User.objects.create_user(
            email='researcher@example.com',
            name='Researcher',
            password='test-password',
        )
        self.researcher._cached_role = 'RESEARCHER'
        self.supervisor = User.objects.create_user(
            email='supervisor@example.com',
            name='Supervisor',
            password='test-password',
        )
        self.supervisor._cached_role = 'SUPERVISOR'
        self.agent = VoiceAgent.objects.create(
            user=self.owner,
            name='Reflection bot',
            system_prompt='Ask reflective questions.',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code='REFLECT-123',
            default_max_attempts=3,
        )
        self.client.force_authenticate(self.student)

    def test_redeeming_access_code_inherits_agent_attempt_default(self):
        response = self.client.post(
            '/api/voice/agents/redeem_access_code/',
            {'access_code': self.agent.access_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = VoiceAgentAccess.objects.get(agent=self.agent, user=self.student)
        self.assertEqual(access.max_attempts, 3)

    def test_redeeming_again_preserves_student_override(self):
        VoiceAgentAccess.objects.create(
            agent=self.agent,
            user=self.student,
            max_attempts=5,
        )

        response = self.client.post(
            '/api/voice/agents/redeem_access_code/',
            {'access_code': self.agent.access_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access = VoiceAgentAccess.objects.get(agent=self.agent, user=self.student)
        self.assertEqual(access.max_attempts, 5)

    def test_creator_and_researcher_can_subscribe_without_losing_owned_agents(self):
        for scoped_user in (self.creator, self.researcher):
            with self.subTest(platform_role=scoped_user.platform_role):
                own_agent = VoiceAgent.objects.create(
                    user=scoped_user,
                    name=f'{scoped_user.platform_role.title()}-owned bot',
                    system_prompt='Ask scoped questions.',
                    status=VoiceAgentStatus.ACTIVE,
                    voice_provider=VoiceProvider.MISTRAL_VOICE,
                )
                self.client.force_authenticate(scoped_user)

                response = self.client.post(
                    '/api/voice/agents/redeem_access_code/',
                    {'access_code': self.agent.access_code},
                    format='json',
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(
                    VoiceAgentAccess.objects.filter(agent=self.agent, user=scoped_user).exists()
                )
                list_response = self.client.get('/api/voice/agents/')
                visible_agent_ids = {agent['id'] for agent in list_response.data}
                self.assertEqual(visible_agent_ids, {self.agent.id, own_agent.id})

    def test_supervisor_cannot_redeem_access_code(self):
        self.client.force_authenticate(self.supervisor)

        response = self.client.post(
            '/api/voice/agents/redeem_access_code/',
            {'access_code': self.agent.access_code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(
            VoiceAgentAccess.objects.filter(agent=self.agent, user=self.supervisor).exists()
        )

    def test_agent_attempt_default_must_be_positive(self):
        serializer = VoiceAgentUpdateSerializer(
            self.agent,
            data={'default_max_attempts': 0},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('default_max_attempts', serializer.errors)

    def test_owner_can_clone_agent_configuration_as_draft(self):
        self.client.force_authenticate(self.owner)

        response = self.client.post(f'/api/voice/agents/{self.agent.id}/clone/')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        clone = VoiceAgent.objects.get(pk=response.data['id'])
        self.assertEqual(clone.name, f'Copy of {self.agent.name}')
        self.assertEqual(clone.user, self.owner)
        self.assertEqual(clone.status, VoiceAgentStatus.DRAFT)
        self.assertEqual(clone.voice_provider, self.agent.voice_provider)
        self.assertEqual(clone.system_prompt, self.agent.system_prompt)
        self.assertEqual(clone.default_max_attempts, self.agent.default_max_attempts)
        self.assertEqual(clone.access_code, '')
        self.assertFalse(clone.student_accesses.exists())
        self.assertFalse(clone.conversations.exists())

    def test_manager_delete_hides_attempt_and_releases_attempt_count(self):
        VoiceAgentAccess.objects.create(
            agent=self.agent,
            user=self.student,
            max_attempts=3,
        )
        conversation = VoiceConversation.objects.create(
            agent=self.agent,
            user=self.student,
            elevenlabs_conversation_id='completed-delete-test',
            provider_conversation_id='completed-delete-test',
            status=ConversationStatus.COMPLETED,
        )
        self.client.force_authenticate(self.owner)

        before = self.client.get(f'/api/voice/agents/{self.agent.id}/students/')
        response = self.client.delete(f'/api/voice/conversations/{conversation.id}/')
        after = self.client.get(f'/api/voice/agents/{self.agent.id}/students/')

        self.assertEqual(before.data[0]['attempts_used'], 1)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        conversation.refresh_from_db()
        self.assertTrue(conversation.is_deleted)
        self.assertFalse(conversation.is_active)
        self.assertEqual(after.data[0]['attempts_used'], 0)

    def test_student_cannot_delete_own_attempt(self):
        VoiceAgentAccess.objects.create(agent=self.agent, user=self.student)
        conversation = VoiceConversation.objects.create(
            agent=self.agent,
            user=self.student,
            elevenlabs_conversation_id='student-delete-test',
            provider_conversation_id='student-delete-test',
            status=ConversationStatus.COMPLETED,
        )

        response = self.client.delete(f'/api/voice/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        conversation.refresh_from_db()
        self.assertFalse(conversation.is_deleted)

    def test_active_attempt_cannot_be_deleted(self):
        conversation = VoiceConversation.objects.create(
            agent=self.agent,
            user=self.student,
            elevenlabs_conversation_id='active-delete-test',
            provider_conversation_id='active-delete-test',
            status=ConversationStatus.IN_PROGRESS,
        )
        self.client.force_authenticate(self.owner)

        response = self.client.delete(f'/api/voice/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        conversation.refresh_from_db()
        self.assertFalse(conversation.is_deleted)


class VoiceAccessCodeSignupIntegrationTests(APITestCase):
    """Researcher accounts created through a voice code: agent creation and scope."""

    def setUp(self):
        User = get_user_model()
        self.inviter = User.objects.create_user(
            email='inviter@example.com', name='Inviter', password='test-password'
        )
        self.inviter_agent = VoiceAgent.objects.create(
            user=self.inviter,
            name='Inviter exam',
            system_prompt='Examine.',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code='INVITE-1',
            default_max_attempts=2,
        )
        self.researcher = User.objects.create_user(
            email='new-researcher@example.com', name='New Researcher', password='test-password'
        )
        self.researcher._cached_role = 'RESEARCHER'
        VoiceAgentAccess.objects.create(
            agent=self.inviter_agent, user=self.researcher, max_attempts=2
        )
        self.client.force_authenticate(self.researcher)

        dare = patch('voice.access_codes.auth_client')
        self.voice_dare = dare.start()
        self.addCleanup(dare.stop)
        self.voice_dare.provision_voice_access_code.return_value = {'success': True}

    def test_new_researcher_sees_assignment_as_student_and_cannot_manage_it(self):
        detail = self.client.get(f'/api/voice/agents/{self.inviter_agent.id}/')
        edit = self.client.patch(
            f'/api/voice/agents/{self.inviter_agent.id}/', {'name': 'Hijacked'}, format='json'
        )
        delete = self.client.delete(f'/api/voice/agents/{self.inviter_agent.id}/')
        students = self.client.get(f'/api/voice/agents/{self.inviter_agent.id}/students/')

        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['permissions']['accessLevel'], 'student')
        self.assertTrue(detail.data['permissions']['canLaunchExam'])
        self.assertFalse(detail.data['permissions']['canEdit'])
        self.assertIsNone(detail.data['access_code_for_admin'])
        self.assertEqual(edit.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(students.status_code, status.HTTP_403_FORBIDDEN)
        self.inviter_agent.refresh_from_db()
        self.assertEqual(self.inviter_agent.name, 'Inviter exam')

    def test_new_researcher_can_create_own_agent_and_its_code_is_provisioned(self):
        response = self.client.post(
            '/api/voice/agents/',
            {
                'name': 'My first agent',
                'system_prompt': 'Ask questions.',
                'voice_provider': VoiceProvider.MISTRAL_VOICE,
                'access_code': ' MINE-1 ',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        agent = VoiceAgent.objects.get(pk=response.data['id'])
        self.assertEqual(agent.user, self.researcher)
        self.assertEqual(agent.access_code, 'MINE-1')
        self.voice_dare.provision_voice_access_code.assert_called_once_with(
            'MINE-1', action='ensure', activate=True
        )

    def test_student_role_cannot_create_agents(self):
        self.researcher._cached_role = 'USER'

        response = self.client.post(
            '/api/voice/agents/',
            {'name': 'Nope', 'system_prompt': 'x', 'voice_provider': VoiceProvider.MISTRAL_VOICE},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_agent_code_cannot_collide_with_a_bot_code_or_another_creators_code(self):
        from access_codes.models import SubscriptionCode
        from bots.models import Bot, BotGroup

        group = BotGroup.objects.create(owner=self.inviter, title='Intro')
        bot = Bot.objects.create(
            bot_group=group, user=self.inviter, title='Tutor', subject='Math', topic='Algebra'
        )
        SubscriptionCode.objects.create(code='BOARD-9', bot=bot, created_by=self.inviter, limit=5)

        board = self.client.post(
            '/api/voice/agents/',
            {'name': 'A', 'system_prompt': 'x', 'voice_provider': VoiceProvider.MISTRAL_VOICE,
             'access_code': 'BOARD-9'},
            format='json',
        )
        foreign = self.client.post(
            '/api/voice/agents/',
            {'name': 'B', 'system_prompt': 'x', 'voice_provider': VoiceProvider.MISTRAL_VOICE,
             'access_code': 'INVITE-1'},
            format='json',
        )

        self.assertEqual(board.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('access_code', board.data)
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('access_code', foreign.data)
        self.voice_dare.provision_voice_access_code.assert_not_called()

    def test_changing_or_removing_a_code_releases_it_in_dare_only_when_unused(self):
        self.client.force_authenticate(self.inviter)
        sibling = VoiceAgent.objects.create(
            user=self.inviter,
            name='Sibling',
            system_prompt='x',
            status=VoiceAgentStatus.ACTIVE,
            voice_provider=VoiceProvider.MISTRAL_VOICE,
            access_code='INVITE-1',
        )

        self.client.patch(
            f'/api/voice/agents/{self.inviter_agent.id}/', {'access_code': 'INVITE-2'}, format='json'
        )
        self.voice_dare.provision_voice_access_code.assert_called_once_with(
            'INVITE-2', action='ensure', activate=True
        )

        self.voice_dare.provision_voice_access_code.reset_mock()
        self.client.delete(f'/api/voice/agents/{sibling.id}/')
        self.voice_dare.provision_voice_access_code.assert_called_once_with(
            'INVITE-1', action='deactivate'
        )

    def test_code_already_used_by_a_dare_registration_code_is_refused_at_save(self):
        self.voice_dare.provision_voice_access_code.return_value = {'conflict': True}

        response = self.client.post(
            '/api/voice/agents/',
            {'name': 'Clash', 'system_prompt': 'x', 'voice_provider': VoiceProvider.MISTRAL_VOICE,
             'access_code': 'PHIL-101'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already used', str(response.data['access_code'][0]))
        self.assertFalse(VoiceAgent.objects.filter(name='Clash').exists())

    def test_provisioning_outage_blocks_saving_a_new_code_with_a_clear_message(self):
        from utils.dare_api import DareApiError

        self.voice_dare.provision_voice_access_code.side_effect = DareApiError('down')

        response = self.client.post(
            '/api/voice/agents/',
            {'name': 'Resilient', 'system_prompt': 'x', 'voice_provider': VoiceProvider.MISTRAL_VOICE,
             'access_code': 'RES-1'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('try again', str(response.data['access_code'][0]).lower())
        self.assertFalse(VoiceAgent.objects.filter(name='Resilient').exists())

    def test_saving_without_changing_the_code_does_not_call_dare(self):
        self.client.force_authenticate(self.inviter)

        response = self.client.patch(
            f'/api/voice/agents/{self.inviter_agent.id}/',
            {'name': 'Renamed', 'access_code': 'INVITE-1'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.voice_dare.provision_voice_access_code.assert_not_called()
