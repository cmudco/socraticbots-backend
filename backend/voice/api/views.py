# voice/api/views.py
"""
API Views for Voice agents and conversations.
"""

import copy
import io
import logging
import os
import tempfile
import zipfile

import weasyprint

from django.contrib.auth import get_user_model
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Q, Prefetch
from asgiref.sync import async_to_sync

from utils.helpers import slugify, get_user_display_name
from voice.models import (
    VoiceAgent, VoiceAgentAccess, VoiceConversation,
    VoiceTeam, VoiceTeamMembership, VoiceAgentMembership,
)
from voice.constants import (
    ConversationStatus, VoiceAgentStatus, VoiceProvider, VoiceTeamRole,
    parse_elevenlabs_agent_name, agent_belongs_to_user,
)
from voice.access_codes import release_agent_code_in_dare
from voice.access import (
    resolve_access, get_accessible_agents_queryset,
    can_create_voice_agents,
    CAN_EDIT, CAN_DELETE, CAN_MANAGE_ACCESS,
)
from voice.services.elevenlabs_service import ElevenLabsService
from voice.services.providers import get_voice_provider
from voice.services.session_service import VoiceSessionError, VoiceSessionService
from voice.services.browser_diagnostics import (
    BrowserDiagnosticSerializer, BrowserDiagnosticThrottle, save_browser_diagnostic,
)
from .serializers import (
    VoiceAgentSerializer,
    VoiceAgentListSerializer,
    VoiceAgentCreateSerializer,
    VoiceAgentUpdateSerializer,
    VoiceConversationSerializer,
    VoiceConversationListSerializer,
    VoiceTeamSerializer,
    VoiceTeamWithMembersSerializer,
    VoiceTeamMembershipSerializer,
    VoiceAgentMembershipSerializer,
    StartConversationSerializer,
    EndConversationSerializer,
    CancelConversationSerializer,
)

logger = logging.getLogger(__name__)


class VoiceAgentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing ElevenLabs Voice Agents.

    Team-aware access resolution:
    - Supervisors see all agents
    - Owners see agents they created
    - Team members see agents in their teams
    - Students see agents they've unlocked via access code
    """
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'], throttle_classes=[BrowserDiagnosticThrottle])
    def browser_diagnostics(self, request, pk=None):
        agent = self.get_object()
        if not resolve_access(request.user, agent):
            return Response({'error': 'Agent not available.'}, status=403)
        serializer = BrowserDiagnosticSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        save_browser_diagnostic(agent=agent, user=request.user, data=serializer.validated_data)
        return Response(status=204)

    def get_queryset(self):
        """Return agents the user can access via any scope."""
        user = self.request.user
        if self.action == 'list':
            return get_accessible_agents_queryset(user)
        # For detail/action views, broad queryset — permission checked per-action
        return VoiceAgent.objects.filter(is_deleted=False)

    def get_serializer_class(self):
        if self.action == 'list':
            return VoiceAgentListSerializer
        if self.action == 'create':
            return VoiceAgentCreateSerializer
        if self.action in ['update', 'partial_update']:
            return VoiceAgentUpdateSerializer
        return VoiceAgentSerializer

    def create(self, request, *args, **kwargs):
        """Create a new voice agent and provision it with the selected provider."""
        user = request.user

        # Creators can create personal agents; team assignment requires a team manager
        # or supervisor.
        manager_teams = list(
            VoiceTeamMembership.objects.filter(
                user=user, role=VoiceTeamRole.MANAGER
            ).values_list('team_id', flat=True)
        )

        if not can_create_voice_agents(user):
            return Response(
                {"error": "Only creators, supervisors, or team managers can create voice agents"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Team assignment logic (team is optional)
        team = serializer.validated_data.get('team')

        if team and not user.is_supervisor_or_above:
            # Verify user is manager of the specified team
            if team.pk not in manager_teams:
                return Response(
                    {"error": "You are not a manager of the specified team"},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Save to local DB first
        agent = serializer.save(user=request.user, team=team)

        # Provision provider-side resources when needed.
        try:
            provider = get_voice_provider(agent.voice_provider)
            provider.create_agent(agent)

        except Exception as e:
            # Rollback local creation if provider provisioning fails
            logger.error(f"Failed to create voice provider agent: {e}")
            agent.delete()
            return Response(
                {"error": f"Failed to create voice provider agent: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            VoiceAgentSerializer(agent, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        """Update agent and sync changes to the selected provider."""
        instance = self.get_object()
        previous_provider = instance.voice_provider
        previous_code = instance.access_code

        access = resolve_access(request.user, instance)
        if not access or access not in CAN_EDIT:
            return Response(
                {"error": "You do not have permission to edit this agent"},
                status=status.HTTP_403_FORBIDDEN
            )

        partial = kwargs.pop('partial', False)
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        agent = serializer.save()

        if agent.access_code != previous_code:
            release_agent_code_in_dare(previous_code)

        try:
            provider = get_voice_provider(agent.voice_provider)
            if previous_provider != agent.voice_provider:
                provider.create_agent(agent)
            else:
                provider.update_agent(agent)
        except Exception as e:
            logger.error(f"Voice provider sync failed: {e}")
            return Response(
                {
                    "warning": f"Local update saved but voice provider sync failed: {str(e)}",
                    "data": VoiceAgentSerializer(agent, context={'request': request}).data
                },
                status=status.HTTP_207_MULTI_STATUS
            )

        return Response(VoiceAgentSerializer(agent, context={'request': request}).data)

    def destroy(self, request, *args, **kwargs):
        """Delete agent from local DB and provider."""
        instance = self.get_object()

        access = resolve_access(request.user, instance)
        if not access or access not in CAN_DELETE:
            return Response(
                {"error": "You do not have permission to delete this agent"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            provider = get_voice_provider(instance.voice_provider)
            provider.delete_agent(instance)
        except Exception as e:
            logger.error(f"Failed to delete from voice provider: {e}")
            return Response(
                {"error": f"Failed to delete from voice provider: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Soft delete locally
        instance.soft_delete()
        release_agent_code_in_dare(instance.access_code)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        """Clone an agent's configuration into a new draft agent."""
        source = self.get_object()
        access = resolve_access(request.user, source)

        if not access or access not in CAN_EDIT:
            return Response(
                {"error": "You do not have permission to clone this agent"},
                status=status.HTTP_403_FORBIDDEN,
            )

        cloned_agent = VoiceAgent.objects.create(
            user=request.user,
            name=f"Copy of {source.name}"[:255],
            description=source.description,
            team=source.team,
            voice_id=source.voice_id,
            voice_provider=source.voice_provider,
            language=source.language,
            system_prompt=source.system_prompt,
            first_message=source.first_message,
            temperature=source.temperature,
            max_duration_seconds=source.max_duration_seconds,
            voice_eagerness=source.voice_eagerness,
            voice_turn_mode=source.voice_turn_mode,
            voice_turn_timeout_secs=source.voice_turn_timeout_secs,
            llm_model=source.llm_model,
            conversation_config=copy.deepcopy(source.conversation_config),
            exam_title=source.exam_title,
            exam_instructions=source.exam_instructions,
            default_max_attempts=source.default_max_attempts,
            status=VoiceAgentStatus.DRAFT,
            access_code='',
        )

        try:
            get_voice_provider(cloned_agent.voice_provider).create_agent(cloned_agent)
        except Exception as exc:
            logger.error("Failed to provision cloned voice agent: %s", exc)
            cloned_agent.delete()
            return Response(
                {"error": f"Failed to provision cloned voice agent: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            VoiceAgentSerializer(cloned_agent, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def get_signed_url(self, request, pk=None):
        """Get provider-aware connection details for this agent."""
        agent = self.get_object()
        try:
            session = VoiceSessionService().start_session(agent, request.user)
            return Response(session.to_response_data())
        except VoiceSessionError as e:
            return Response({"error": e.message, "code": e.code}, status=e.status_code)
        except Exception as e:
            logger.exception("Failed to start voice session")
            return Response(
                {"error": f"Failed to start voice session: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['get'])
    def session_status(self, request, pk=None):
        """Confirm persistence, not merely receipt of a browser end command."""
        agent = self.get_object()
        conversation = VoiceConversation.objects.filter(
            agent=agent, user=request.user, is_deleted=False,
            provider_conversation_id=request.query_params.get('conversation_id', ''),
        ).first()
        if conversation is None:
            return Response({'error': 'Conversation not found'}, status=404)
        return Response({'status': conversation.status,
                         'ended_reason': (conversation.compliance_receipt or {}).get('endedReason')})

    @action(detail=True, methods=['post'])
    def start_conversation(self, request, pk=None):
        """
        Record the start of a conversation session.

        Called after user successfully connects via the SDK.
        """
        agent = self.get_object()
        if agent.voice_provider != VoiceProvider.ELEVENLABS:
            return Response(
                {"error": "Mistral Voice sessions are managed by runtime lifecycle callbacks"},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        elevenlabs_conversation_id = serializer.validated_data['conversation_id']

        try:
            conversation = VoiceSessionService().record_elevenlabs_start(
                agent,
                request.user,
                elevenlabs_conversation_id,
            )
        except VoiceSessionError as e:
            return Response({"error": e.message}, status=e.status_code)

        logger.info(f"Started conversation: {elevenlabs_conversation_id}")

        return Response(
            VoiceConversationSerializer(conversation).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def end_conversation(self, request, pk=None):
        """
        Record the end of a conversation and fetch transcript.

        Idempotent: if conversation is already COMPLETED with a transcript,
        returns the existing data instead of re-fetching from ElevenLabs
        (which may have been deleted by the webhook already).
        """
        agent = self.get_object()
        if agent.voice_provider != VoiceProvider.ELEVENLABS:
            return Response(
                {"error": "Mistral Voice sessions are completed by the runtime callback"},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = EndConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        elevenlabs_conversation_id = serializer.validated_data['conversation_id']

        try:
            conversation = VoiceSessionService().end_elevenlabs_conversation(
                agent,
                request.user,
                elevenlabs_conversation_id,
            )
        except VoiceSessionError as e:
            return Response({"error": e.message}, status=e.status_code)

        return Response(VoiceConversationSerializer(conversation).data)

    @action(detail=True, methods=['post'])
    def cancel_conversation(self, request, pk=None):
        """Mark a provider conversation as cancelled when the client abandons it."""
        agent = self.get_object()
        serializer = CancelConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            conversation = VoiceSessionService().cancel_conversation(
                agent=agent,
                user=request.user,
                conversation_id=serializer.validated_data['conversation_id'],
                ended_reason=serializer.validated_data.get(
                    'ended_reason',
                    'client_cancelled',
                ),
            )
        except VoiceSessionError as e:
            return Response({"error": e.message}, status=e.status_code)

        return Response(VoiceConversationSerializer(conversation).data)

    @action(detail=False, methods=['post'])
    def redeem_access_code(self, request):
        """
        Allow any scoped user to unlock a voice assignment using an access code.

        Supervisors already have global voice-assignment access, so they do not
        participate in access-code subscriptions.

        POST /voice/agents/redeem_access_code/
        Body: { "access_code": "CODE123" }
        """
        if request.user.is_supervisor_or_above:
            return Response(
                {"error": "Supervisors already have access to all voice assignments"},
                status=status.HTTP_403_FORBIDDEN,
            )

        code = request.data.get('access_code', '').strip()
        if not code:
            return Response(
                {"error": "access_code is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        agent = VoiceAgent.objects.filter(
            access_code=code, is_deleted=False, is_active=True
        ).first()

        if not agent:
            return Response(
                {"error": "Invalid access code"},
                status=status.HTTP_400_BAD_REQUEST
            )

        VoiceAgentAccess.objects.get_or_create(
            agent=agent,
            user=request.user,
            defaults={"max_attempts": agent.default_max_attempts},
        )
        logger.info(f"User {request.user.email} redeemed access code for agent {agent.id}")

        return Response(
            VoiceAgentSerializer(agent, context={'request': request}).data,
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def voices(self, request):
        """List available ElevenLabs voices."""
        try:
            service = ElevenLabsService()
            voices = async_to_sync(service.list_voices)()

            # Transform to simpler format
            simplified_voices = [
                {
                    "voice_id": v.get("voice_id"),
                    "name": v.get("name"),
                    "preview_url": v.get("preview_url"),
                    "category": v.get("category"),
                }
                for v in voices
            ]

            return Response(simplified_voices)
        except Exception as e:
            logger.error(f"Failed to fetch voices: {e}")
            return Response(
                {"error": f"Failed to fetch voices: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def elevenlabs_agents(self, request):
        """
        List agents directly from ElevenLabs API.

        Only shows agents that belong to the requesting user (matched by email).
        """
        if not can_create_voice_agents(request.user):
            return Response(
                {"error": "Only creators, supervisors, or team managers can access ElevenLabs agents"},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            service = ElevenLabsService()
            all_agents = async_to_sync(service.list_agents)()

            user_email = request.user.email
            agents = [
                a for a in all_agents
                if agent_belongs_to_user(a.get('name', ''), user_email)
            ]

            # Add local sync status and strip prefix from name for display
            elevenlabs_ids = [a.get('agent_id') for a in agents]
            synced_agents = VoiceAgent.objects.filter(
                elevenlabs_agent_id__in=elevenlabs_ids
            ).values_list('elevenlabs_agent_id', flat=True)
            synced_set = set(synced_agents)

            for agent in agents:
                agent['is_synced'] = agent.get('agent_id') in synced_set
                agent['name'] = parse_elevenlabs_agent_name(agent.get('name', ''))

            return Response(agents)
        except Exception as e:
            logger.error(f"Failed to fetch ElevenLabs agents: {e}")
            return Response(
                {"error": f"Failed to fetch ElevenLabs agents: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def sync_from_elevenlabs(self, request, pk=None):
        """
        Pull the latest agent configuration from ElevenLabs into local DB.
        Updates ElevenLabs-managed fields (name, system_prompt, voice_id, etc.)
        while preserving local-only fields (description, exam_title, etc.).
        """
        agent = self.get_object()

        if not request.user.is_supervisor_or_above and agent.user != request.user:
            return Response(
                {"error": "You can only sync your own agents"},
                status=status.HTTP_403_FORBIDDEN
            )
        if not request.user.is_creator:
            return Response(
                {"error": "Only creators or supervisors can sync voice agents"},
                status=status.HTTP_403_FORBIDDEN
            )
        if not agent.elevenlabs_agent_id:
            return Response(
                {"error": "Agent is not linked to ElevenLabs"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if agent.voice_provider != VoiceProvider.ELEVENLABS:
            return Response(
                {"error": "Only ElevenLabs agents can sync from ElevenLabs"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = ElevenLabsService()
            agent_data = async_to_sync(service.get_agent)(agent.elevenlabs_agent_id)

            conv_config = agent_data.get('conversation_config', {})
            agent_config = conv_config.get('agent', {})
            prompt_config = agent_config.get('prompt', {})
            tts_config = conv_config.get('tts', {})
            conversation_settings = conv_config.get('conversation', {})

            elevenlabs_name = agent_data.get('name', '')
            display_name = parse_elevenlabs_agent_name(elevenlabs_name)

            agent.name = display_name
            agent.system_prompt = prompt_config.get('prompt', '')
            agent.voice_id = tts_config.get('voice_id', '')
            agent.first_message = agent_config.get('first_message', '')
            agent.temperature = prompt_config.get('temperature', 0.7)
            agent.max_duration_seconds = conversation_settings.get('max_duration_seconds', 1800)
            agent.conversation_config = conv_config
            agent.save(update_fields=[
                'name', 'system_prompt', 'voice_id', 'first_message',
                'temperature', 'max_duration_seconds', 'conversation_config',
            ])

            logger.info(f"Synced agent {agent.id} from ElevenLabs: {agent.elevenlabs_agent_id}")
            return Response(VoiceAgentSerializer(agent, context={'request': request}).data)

        except Exception as e:
            logger.error(f"Failed to sync from ElevenLabs: {e}")
            return Response(
                {"error": f"Failed to sync from ElevenLabs: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def import_agent(self, request):
        """
        Import an existing ElevenLabs agent into local database.

        This allows users to sync agents that were created directly
        in ElevenLabs dashboard or via other means.
        Available to creators, supervisors, and team managers.
        """
        if not can_create_voice_agents(request.user):
            return Response(
                {"error": "Only creators, supervisors, or team managers can import agents"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Support both camelCase (from frontend) and snake_case
        elevenlabs_agent_id = request.data.get('agentId') or request.data.get('agent_id')
        if not elevenlabs_agent_id:
            return Response(
                {"error": "agent_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if already synced
        if VoiceAgent.objects.filter(elevenlabs_agent_id=elevenlabs_agent_id).exists():
            return Response(
                {"error": "Agent already imported"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = ElevenLabsService()
            agent_data = async_to_sync(service.get_agent)(elevenlabs_agent_id)

            # Verify the agent belongs to this instructor via naming convention
            elevenlabs_name = agent_data.get('name', '')
            if not agent_belongs_to_user(elevenlabs_name, request.user.email):
                return Response(
                    {"error": "This agent does not belong to you. "
                     "Only agents following the naming convention "
                     "(email_prefix__agent_name) can be imported."},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Extract data from ElevenLabs response
            conv_config = agent_data.get('conversation_config', {})
            agent_config = conv_config.get('agent', {})
            prompt_config = agent_config.get('prompt', {})
            tts_config = conv_config.get('tts', {})
            conversation_settings = conv_config.get('conversation', {})

            # Store display name (without prefix) locally
            display_name = parse_elevenlabs_agent_name(elevenlabs_name)

            # Create local agent with full config
            agent = VoiceAgent.objects.create(
                user=request.user,
                voice_provider=VoiceProvider.ELEVENLABS,
                elevenlabs_agent_id=elevenlabs_agent_id,
                name=display_name,
                system_prompt=prompt_config.get('prompt', ''),
                voice_id=tts_config.get('voice_id', ''),
                first_message=agent_config.get('first_message', ''),
                temperature=prompt_config.get('temperature', 0.7),
                max_duration_seconds=conversation_settings.get('max_duration_seconds', 1800),
                conversation_config=conv_config,  # Store full ElevenLabs config
                status=VoiceAgentStatus.ACTIVE,
            )

            logger.info(f"Imported ElevenLabs agent: {elevenlabs_agent_id}")

            # Attach webhook to the imported agent
            async_to_sync(service.ensure_webhook)(elevenlabs_agent_id)

            return Response(
                VoiceAgentSerializer(agent).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Failed to import agent: {e}")
            return Response(
                {"error": f"Failed to import agent: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ── Team Discovery ──────────────────────────────────

    @action(detail=False, methods=['get'], url_path='my_teams')
    def my_teams(self, request):
        """Return teams the user manages, with full member lists.

        Supervisors see all active teams.
        Managers see only teams they manage.
        """
        user = request.user
        membership_qs = VoiceTeamMembership.objects.select_related('user', 'granted_by')

        if user.is_supervisor_or_above:
            teams = VoiceTeam.objects.filter(
                is_deleted=False, is_active=True
            ).prefetch_related(
                Prefetch('memberships', queryset=membership_qs)
            )
        else:
            manager_team_ids = VoiceTeamMembership.objects.filter(
                user=user, role=VoiceTeamRole.MANAGER
            ).values_list('team_id', flat=True)
            teams = VoiceTeam.objects.filter(
                Q(pk__in=manager_team_ids) | Q(created_by=user),
                is_deleted=False, is_active=True
            ).distinct().prefetch_related(
                Prefetch('memberships', queryset=membership_qs)
            )

        serializer = VoiceTeamWithMembersSerializer(teams, many=True)
        return Response(serializer.data)

    # ── Shared Access Management ─────────────────────────

    @action(detail=True, methods=['get'], url_path='members')
    def list_members(self, request, pk=None):
        """List all team and agent-level memberships for this agent."""
        agent = self.get_object()
        access = resolve_access(request.user, agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to view members"},
                status=status.HTTP_403_FORBIDDEN
            )

        result = {
            'team_members': [],
            'agent_members': [],
        }

        if agent.team_id:
            team_memberships = VoiceTeamMembership.objects.filter(
                team_id=agent.team_id
            ).select_related('user', 'granted_by')
            result['team_members'] = VoiceTeamMembershipSerializer(
                team_memberships, many=True
            ).data

        agent_memberships = VoiceAgentMembership.objects.filter(
            agent=agent
        ).select_related('user', 'granted_by')
        result['agent_members'] = VoiceAgentMembershipSerializer(
            agent_memberships, many=True
        ).data

        return Response(result)

    @action(detail=True, methods=['post'], url_path='add-member')
    def add_member(self, request, pk=None):
        """
        Add a team or agent-level membership.

        Body: { "email": "...", "role": "reviewer", "scope": "team"|"agent" }
        """
        agent = self.get_object()
        access = resolve_access(request.user, agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to manage members"},
                status=status.HTTP_403_FORBIDDEN
            )

        email = request.data.get('email', '').strip()
        role = request.data.get('role', '').strip()
        scope = request.data.get('scope', 'agent').strip()

        if not email or not role:
            return Response(
                {"error": "email and role are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Only manager and reviewer for now (admin reserved for future Co-Admin)
        if scope == 'team' and role not in ['manager', 'reviewer']:
            return Response(
                {"error": "Team role must be 'manager' or 'reviewer'"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if scope == 'agent' and role not in ['reviewer']:
            return Response(
                {"error": "Agent role must be 'reviewer'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        User = get_user_model()
        try:
            target_user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": f"User with email '{email}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if scope == 'team':
            if not agent.team_id:
                return Response(
                    {"error": "Agent does not belong to a team"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            membership, created = VoiceTeamMembership.objects.update_or_create(
                team_id=agent.team_id,
                user=target_user,
                defaults={'role': role, 'granted_by': request.user},
            )
            return Response(
                VoiceTeamMembershipSerializer(membership).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
            )
        else:
            membership, created = VoiceAgentMembership.objects.update_or_create(
                agent=agent,
                user=target_user,
                defaults={'role': role, 'granted_by': request.user},
            )
            return Response(
                VoiceAgentMembershipSerializer(membership).data,
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
            )

    @action(detail=True, methods=['post'], url_path='remove-member')
    def remove_member(self, request, pk=None):
        """
        Remove a team or agent-level membership.

        Body: { "membership_id": 123, "scope": "team"|"agent" }
        """
        agent = self.get_object()
        access = resolve_access(request.user, agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to manage members"},
                status=status.HTTP_403_FORBIDDEN
            )

        membership_id = request.data.get('membership_id')
        scope = request.data.get('scope', 'agent').strip()

        if not membership_id:
            return Response(
                {"error": "membership_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if scope == 'team':
            deleted, _ = VoiceTeamMembership.objects.filter(
                pk=membership_id, team_id=agent.team_id
            ).delete()
        else:
            deleted, _ = VoiceAgentMembership.objects.filter(
                pk=membership_id, agent=agent
            ).delete()

        if not deleted:
            return Response(
                {"error": "Membership not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Student Attempt Management ────────────────────────

    @action(detail=True, methods=['get'], url_path='students')
    def list_students(self, request, pk=None):
        """
        List students who have accessed this exam, with attempt counts.

        Only accessible by CAN_MANAGE_ACCESS roles (supervisor, owner, manager).
        """
        agent = self.get_object()
        access = resolve_access(request.user, agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to view students"},
                status=status.HTTP_403_FORBIDDEN
            )

        accesses = VoiceAgentAccess.objects.filter(
            agent=agent
        ).select_related('user')

        result = []
        for sa in accesses:
            attempt_count = VoiceConversation.objects.filter(
                agent=agent,
                user=sa.user,
                is_deleted=False,
                is_active=True,
                status__in=[ConversationStatus.COMPLETED, ConversationStatus.IN_PROGRESS]
            ).count()

            result.append({
                "user_id": sa.user.id,
                "email": sa.user.email,
                "max_attempts": sa.max_attempts,
                "attempts_used": attempt_count,
                "can_retake": attempt_count < sa.max_attempts,
                "access_granted_at": sa.created_at.isoformat(),
            })

        return Response(result)

    @action(detail=True, methods=['post'], url_path='grant-retake')
    def grant_retake(self, request, pk=None):
        """
        Grant a student additional exam attempts.

        Body: { "email": "student@example.com", "max_attempts": 2 }
        """
        agent = self.get_object()
        access = resolve_access(request.user, agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to grant retakes"},
                status=status.HTTP_403_FORBIDDEN
            )

        email = request.data.get('email', '').strip()
        max_attempts = request.data.get('max_attempts')

        if not email or max_attempts is None:
            return Response(
                {"error": "email and max_attempts are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            max_attempts = int(max_attempts)
            if max_attempts < 1:
                raise ValueError
        except (ValueError, TypeError):
            return Response(
                {"error": "max_attempts must be a positive integer"},
                status=status.HTTP_400_BAD_REQUEST
            )

        User = get_user_model()
        try:
            student = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"error": f"User with email '{email}' not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        student_access = VoiceAgentAccess.objects.filter(
            agent=agent, user=student
        ).first()

        if not student_access:
            return Response(
                {"error": "Student has not redeemed access to this exam"},
                status=status.HTTP_404_NOT_FOUND
            )

        student_access.max_attempts = max_attempts
        student_access.save(update_fields=['max_attempts'])

        return Response({
            "email": email,
            "max_attempts": max_attempts,
            "message": f"Updated max attempts to {max_attempts}"
        })


class VoiceConversationViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing voice conversations.

    Team-aware access:
    - Supervisors see all conversations
    - Owners/managers/admins/reviewers see conversations for agents they can access
    - Students see only their own conversations
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if user.is_supervisor_or_above:
            qs = VoiceConversation.objects.filter(is_deleted=False, is_active=True)
        else:
            # Own conversations
            q = Q(user=user)
            # Conversations on agents user owns
            q |= Q(agent__user=user)
            # Conversations on agents in user's teams (for managers/admins/reviewers)
            team_ids = VoiceTeamMembership.objects.filter(
                user=user
            ).values_list('team_id', flat=True)
            if team_ids:
                q |= Q(agent__team_id__in=team_ids)
            # Conversations on agents user has direct membership on
            agent_ids = VoiceAgentMembership.objects.filter(
                user=user
            ).values_list('agent_id', flat=True)
            if agent_ids:
                q |= Q(agent_id__in=agent_ids)

            qs = VoiceConversation.objects.filter(
                q, is_deleted=False, is_active=True
            ).distinct()

        qs = qs.select_related('agent', 'user', 'browser_diagnostic')

        # Optional filter by agent
        agent_id = self.request.query_params.get('agent_id')
        if agent_id:
            qs = qs.filter(agent_id=agent_id)

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return VoiceConversationListSerializer
        return VoiceConversationSerializer

    def retrieve(self, request, *args, **kwargs):
        """
        Get a single conversation.
        
        If the conversation is completed but has no transcript,
        automatically fetch and sync it from ElevenLabs.
        """
        instance = self.get_object()
        
        # Auto-sync transcript if empty and conversation is completed
        if self._should_sync_transcript(instance):
            self._sync_transcript_from_elevenlabs(instance)
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """Hide a completed attempt and release it from the student's attempt count."""
        conversation = self.get_object()
        access = resolve_access(request.user, conversation.agent)

        if not access or access not in CAN_MANAGE_ACCESS:
            return Response(
                {"error": "You do not have permission to delete this conversation"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if conversation.status in {
            ConversationStatus.RESERVED,
            ConversationStatus.IN_PROGRESS,
        }:
            return Response(
                {"error": "An active conversation cannot be deleted"},
                status=status.HTTP_409_CONFLICT,
            )

        conversation.is_deleted = True
        conversation.is_active = False
        conversation.save(update_fields=['is_deleted', 'is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def sync_transcript(self, request, pk=None):
        """
        Manually sync transcript from ElevenLabs.
        
        Use this if the transcript is missing or needs to be refreshed.
        """
        conversation = self.get_object()
        
        if conversation.status == ConversationStatus.IN_PROGRESS:
            return Response(
                {"error": "Cannot sync transcript for an in-progress conversation"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            self._sync_transcript_from_elevenlabs(conversation, force=True)
            return Response(VoiceConversationSerializer(conversation).data)
        except Exception as e:
            logger.error(f"Manual transcript sync failed: {e}")
            return Response(
                {"error": f"Failed to sync transcript: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _should_sync_transcript(self, conversation: VoiceConversation) -> bool:
        """Check if conversation needs transcript sync."""
        # Only sync if completed and transcript is empty
        if conversation.status != ConversationStatus.COMPLETED:
            return False
        if conversation.agent.voice_provider != VoiceProvider.ELEVENLABS:
            return False
        
        # Check if transcript is empty (None, empty list, or empty dict)
        transcript = conversation.transcript
        if transcript is None:
            return True
        if isinstance(transcript, list) and len(transcript) == 0:
            return True
        if isinstance(transcript, dict) and len(transcript) == 0:
            return True
        
        return False

    def _sync_transcript_from_elevenlabs(
        self,
        conversation: VoiceConversation,
        force: bool = False
    ) -> None:
        """
        Fetch and save transcript from ElevenLabs API.
        
        Args:
            conversation: The conversation to sync
            force: If True, sync even if transcript exists
        """
        if not force and not self._should_sync_transcript(conversation):
            return
        if conversation.agent.voice_provider != VoiceProvider.ELEVENLABS:
            if force:
                raise ValueError("Only ElevenLabs conversations can be synced from ElevenLabs")
            return
        
        try:
            service = ElevenLabsService()
            conv_data = async_to_sync(service.get_conversation)(
                conversation.elevenlabs_conversation_id
            )
            
            transcript = conv_data.get('transcript', [])
            
            # Only update if we got actual transcript data
            if transcript:
                conversation.transcript = transcript
                conversation.save(update_fields=['transcript'])
                logger.info(
                    f"Synced transcript for conversation "
                    f"{conversation.elevenlabs_conversation_id}: {len(transcript)} messages"
                )
            else:
                logger.info(
                    f"ElevenLabs returned empty transcript for "
                    f"{conversation.elevenlabs_conversation_id}"
                )
                
        except Exception as e:
            logger.error(
                f"Failed to sync transcript for "
                f"{conversation.elevenlabs_conversation_id}: {e}"
            )
            # Don't re-raise for auto-sync, let the request continue
            if force:
                raise

    @action(detail=True, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request, pk=None):
        """
        Export conversation transcript as a PDF.
        """
        conversation = self.get_object()

        try:
            # Format duration
            duration = '-'
            if conversation.duration_seconds:
                mins = conversation.duration_seconds // 60
                secs = conversation.duration_seconds % 60
                duration = f'{mins}m {secs}s'

            # Format transcript messages with time
            transcript = conversation.transcript or []
            for message in transcript:
                time_secs = message.get('timeInCallSecs', message.get('time_in_call_secs', 0))
                mins = int(time_secs // 60)
                secs = int(time_secs % 60)
                message['time_formatted'] = f'{mins}:{secs:02d}'

            # Get student display name
            student_name = get_user_display_name(conversation.user)

            # Prepare context
            context = {
                'agent_name': conversation.agent.name,
                'student_name': student_name,
                'status': conversation.status,
                'duration': duration,
                'started_at': conversation.started_at,
                'ended_at': conversation.ended_at,
                'transcript': transcript,
                'generated_at': timezone.now(),
            }

            # Render HTML template
            html_content = render_to_string('voice/transcript_export.html', context)

            # Generate PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                weasyprint.HTML(string=html_content).write_pdf(tmp_file.name)

                with open(tmp_file.name, 'rb') as pdf_file:
                    pdf_content = pdf_file.read()

                os.unlink(tmp_file.name)

            # Generate filename with student name
            agent_slug = slugify(conversation.agent.name)
            student_slug = slugify(student_name)
            stamp = conversation.started_at.strftime('%Y-%m-%d-%H%M%S')
            filename = f'transcript-{agent_slug}-{student_slug}-{stamp}.pdf'

            # Create HTTP response
            response = HttpResponse(pdf_content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            response['Content-Length'] = len(pdf_content)

            return response

        except Exception as e:
            logger.error(f"Error exporting transcript {pk} to PDF: {str(e)}")
            return Response(
                {"error": f"Failed to export transcript: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='export-all')
    def export_all(self, request):
        """
        Export all conversation transcripts as a ZIP of PDFs.
        Only exports conversations that have transcripts.
        """
        conversations = self.get_queryset().exclude(transcript=[]).exclude(transcript__isnull=True)

        if not conversations.exists():
            return Response(
                {"error": "No conversations with transcripts to export."},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for conversation in conversations:
                    try:
                        # Format duration
                        duration = '-'
                        if conversation.duration_seconds:
                            mins = conversation.duration_seconds // 60
                            secs = conversation.duration_seconds % 60
                            duration = f'{mins}m {secs}s'

                        # Format transcript messages with time
                        transcript = list(conversation.transcript or [])
                        for message in transcript:
                            time_secs = message.get('timeInCallSecs', message.get('time_in_call_secs', 0))
                            mins = int(time_secs // 60)
                            secs = int(time_secs % 60)
                            message['time_formatted'] = f'{mins}:{secs:02d}'

                        student_name = get_user_display_name(conversation.user)

                        context = {
                            'agent_name': conversation.agent.name,
                            'student_name': student_name,
                            'status': conversation.status,
                            'duration': duration,
                            'started_at': conversation.started_at,
                            'ended_at': conversation.ended_at,
                            'transcript': transcript,
                            'generated_at': timezone.now(),
                        }

                        html_content = render_to_string('voice/transcript_export.html', context)

                        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                            weasyprint.HTML(string=html_content).write_pdf(tmp_file.name)
                            with open(tmp_file.name, 'rb') as pdf_file:
                                pdf_content = pdf_file.read()
                            os.unlink(tmp_file.name)

                        agent_slug = slugify(conversation.agent.name)
                        student_slug = slugify(student_name)
                        stamp = conversation.started_at.strftime('%Y-%m-%d-%H%M%S')
                        pdf_filename = f'transcript-{agent_slug}-{student_slug}-{stamp}.pdf'

                        zip_file.writestr(pdf_filename, pdf_content)

                    except Exception as e:
                        logger.exception(
                            f"Skipping conversation {conversation.id} during bulk export: {str(e)}"
                        )
                        continue

            zip_content = zip_buffer.getvalue()

            date_str = timezone.now().strftime('%Y-%m-%d')
            zip_filename = f'voice_exams_export_{date_str}.zip'

            response = HttpResponse(zip_content, content_type='application/zip')
            response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
            response['Content-Length'] = len(zip_content)

            return response

        except Exception as e:
            logger.error(f"Error during bulk export: {str(e)}")
            return Response(
                {"error": f"Failed to export transcripts: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
