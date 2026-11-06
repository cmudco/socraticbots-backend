# voice/api/serializers.py
"""
Serializers for Voice API.
"""

from rest_framework import serializers
from voice.constants import (
    MISTRAL_SUPPORTED_LANGUAGES,
    VOICE_BRAIN_MODEL_IDS,
    ConversationStatus,
    VoiceProvider,
)
from voice.dtos import MistralConversationEndedPayload, TranscriptMessage
from voice.models import (
    VoiceAgent, VoiceConversation, VoiceTeam,
    VoiceTeamMembership, VoiceAgentMembership,
)
from voice.access import resolve_access, get_permissions_dict, CAN_EDIT, CAN_MANAGE_ACCESS
from voice.access_codes import (
    VoiceAccessCodeError,
    live_agents_for_code,
    normalize_voice_access_code,
    reserve_agent_code_in_dare,
)
from access_codes.models import SubscriptionCode


# ── Team Serializers ─────────────────────────────────────

class VoiceTeamSerializer(serializers.ModelSerializer):
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = VoiceTeam
        fields = [
            'id', 'name', 'description', 'created_by', 'created_by_email',
            'is_active', 'member_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_member_count(self, obj):
        return obj.memberships.count()


class VoiceTeamMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    granted_by_email = serializers.CharField(source='granted_by.email', read_only=True, default=None)

    class Meta:
        model = VoiceTeamMembership
        fields = [
            'id', 'team', 'user', 'user_email', 'role',
            'granted_by', 'granted_by_email', 'created_at',
        ]
        read_only_fields = ['id', 'granted_by', 'created_at']


class VoiceAgentMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    granted_by_email = serializers.CharField(source='granted_by.email', read_only=True, default=None)

    class Meta:
        model = VoiceAgentMembership
        fields = [
            'id', 'agent', 'user', 'user_email', 'role',
            'granted_by', 'granted_by_email', 'created_at',
        ]
        read_only_fields = ['id', 'granted_by', 'created_at']


class VoiceTeamWithMembersSerializer(serializers.ModelSerializer):
    """Team serializer with nested member list for the my_teams endpoint."""
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    members = VoiceTeamMembershipSerializer(source='memberships', many=True, read_only=True)

    class Meta:
        model = VoiceTeam
        fields = [
            'id', 'name', 'description', 'created_by', 'created_by_email',
            'is_active', 'members', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


# ── Agent Serializers ────────────────────────────────────

class VoiceAgentSerializer(serializers.ModelSerializer):
    """Full serializer for VoiceAgent with all fields."""
    user_email = serializers.CharField(source='user.email', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True, default=None)
    conversation_count = serializers.SerializerMethodField()
    access_code_for_admin = serializers.SerializerMethodField()
    has_user_access = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = VoiceAgent
        fields = [
            'id', 'user', 'user_email', 'name', 'description',
            'team', 'team_name',
            'elevenlabs_agent_id', 'voice_provider', 'voice_id',
            'language', 'system_prompt',
            'first_message', 'temperature', 'max_duration_seconds',
            'voice_eagerness', 'voice_turn_mode', 'voice_turn_timeout_secs', 'llm_model',
            'exam_title', 'exam_instructions', 'default_max_attempts', 'status',
            'conversation_config', 'conversation_count',
            'access_code_for_admin', 'has_user_access', 'permissions',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'elevenlabs_agent_id', 'created_at', 'updated_at']

    def _get_access_level(self, obj):
        """Cached access level for the current request user."""
        request = self.context.get('request')
        if not request:
            return None
        cache_key = f'_voice_access_{obj.pk}'
        if not hasattr(request, cache_key):
            setattr(request, cache_key, resolve_access(request.user, obj))
        return getattr(request, cache_key)

    def get_conversation_count(self, obj):
        access = self._get_access_level(obj)
        qs = obj.conversations.filter(is_deleted=False)
        # Staff see all conversations; students see only their own
        if access and access not in CAN_EDIT and access != 'reviewer':
            request = self.context.get('request')
            if request:
                qs = qs.filter(user=request.user)
        return qs.count()

    def get_access_code_for_admin(self, obj):
        """Expose access code to users with manage-access permission."""
        access = self._get_access_level(obj)
        if access and access in CAN_MANAGE_ACCESS:
            return obj.access_code
        return None

    def get_has_user_access(self, obj):
        request = self.context.get('request')
        if not request:
            return False
        return obj.student_accesses.filter(user=request.user).exists()

    def get_permissions(self, obj):
        access = self._get_access_level(obj)
        return get_permissions_dict(access)


class VoiceAgentListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for agent list view."""
    user_email = serializers.CharField(source='user.email', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True, default=None)
    access_level = serializers.SerializerMethodField()

    class Meta:
        model = VoiceAgent
        fields = [
            'id', 'user', 'user_email', 'name', 'description',
            'team', 'team_name', 'voice_provider', 'status', 'exam_title',
            'access_level', 'created_at'
        ]

    def get_access_level(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        return resolve_access(request.user, obj)


class VoiceAgentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new VoiceAgent."""
    team = serializers.PrimaryKeyRelatedField(
        queryset=VoiceTeam.objects.filter(is_deleted=False, is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = VoiceAgent
        fields = [
            'name', 'description', 'voice_id', 'system_prompt',
            'first_message', 'temperature', 'max_duration_seconds',
            'voice_eagerness', 'voice_turn_mode', 'voice_turn_timeout_secs', 'llm_model',
            'exam_title', 'exam_instructions', 'default_max_attempts',
            'status', 'conversation_config',
            'access_code', 'team', 'voice_provider', 'language',
        ]

    def validate_access_code(self, value):
        return _validate_agent_access_code(value, owner=self.context['request'].user)

    def validate(self, attrs):
        return _validate_provider_fields(attrs)


class VoiceAgentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a VoiceAgent."""
    team = serializers.PrimaryKeyRelatedField(
        queryset=VoiceTeam.objects.filter(is_deleted=False, is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = VoiceAgent
        fields = [
            'name', 'description', 'voice_id', 'system_prompt',
            'first_message', 'temperature', 'max_duration_seconds',
            'voice_eagerness', 'voice_turn_mode', 'voice_turn_timeout_secs', 'llm_model',
            'exam_title', 'exam_instructions', 'default_max_attempts',
            'status', 'conversation_config',
            'access_code', 'team', 'voice_provider', 'language',
        ]

    def validate_access_code(self, value):
        return _validate_agent_access_code(
            value, owner=self.instance.user, current=self.instance.access_code
        )

    def validate(self, attrs):
        return _validate_provider_fields(attrs, instance=self.instance)


class BrowserDiagnosticsMixin:
    def get_browser_diagnostics(self, obj):
        diagnostic = getattr(obj, 'browser_diagnostic', None)
        return diagnostic.events if diagnostic else []


class VoiceConversationSerializer(BrowserDiagnosticsMixin, serializers.ModelSerializer):
    """Serializer for voice conversations."""
    agent_name = serializers.CharField(source='agent.name', read_only=True)
    agent_voice_provider = serializers.CharField(source='agent.voice_provider', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    ended_reason = serializers.CharField(source='compliance_receipt.endedReason', read_only=True, default=None)
    session_activity = serializers.CharField(source='compliance_receipt.metrics.session_health.activity', read_only=True, default=None)
    browser_diagnostics = serializers.SerializerMethodField()

    class Meta:
        model = VoiceConversation
        fields = [
            'id', 'agent', 'agent_name', 'agent_voice_provider', 'user', 'user_email',
            'elevenlabs_conversation_id', 'provider_conversation_id',
            'started_at', 'ended_at',
            'duration_seconds', 'status', 'transcript', 'created_at', 'ended_reason', 'session_activity', 'browser_diagnostics'
        ]
        read_only_fields = [
            'id', 'elevenlabs_conversation_id', 'provider_conversation_id', 'started_at',
            'ended_at', 'duration_seconds', 'transcript', 'created_at'
        ]


class VoiceConversationListSerializer(BrowserDiagnosticsMixin, serializers.ModelSerializer):
    """Lightweight serializer for conversation list."""
    agent_name = serializers.CharField(source='agent.name', read_only=True)
    agent_voice_provider = serializers.CharField(source='agent.voice_provider', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    ended_reason = serializers.CharField(source='compliance_receipt.endedReason', read_only=True, default=None)
    session_activity = serializers.CharField(source='compliance_receipt.metrics.session_health.activity', read_only=True, default=None)
    browser_diagnostics = serializers.SerializerMethodField()

    class Meta:
        model = VoiceConversation
        fields = [
            'id', 'agent', 'agent_name', 'agent_voice_provider', 'user_email',
            'started_at', 'ended_at', 'duration_seconds', 'status', 'ended_reason', 'session_activity', 'browser_diagnostics'
        ]


class StartConversationSerializer(serializers.Serializer):
    """Request serializer for starting a conversation."""
    conversation_id = serializers.CharField(required=True)


class EndConversationSerializer(serializers.Serializer):
    """Request serializer for ending a conversation."""
    conversation_id = serializers.CharField(required=True)


class CancelConversationSerializer(serializers.Serializer):
    """Serializer for cancelling an unfinished provider conversation."""

    conversation_id = serializers.CharField(required=True)
    ended_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default='client_cancelled',
    )


class RuntimeTranscriptMessageSerializer(serializers.Serializer):
    """Serializer for a runtime transcript message."""

    role = serializers.CharField()
    message = serializers.CharField(allow_blank=True)
    time_in_call_secs = serializers.FloatField(required=False, default=0.0)


class MistralConversationEndedSerializer(serializers.Serializer):
    """Serializer for the Mistral voice runtime completion callback."""

    session_id = serializers.CharField()
    transcript = RuntimeTranscriptMessageSerializer(many=True, required=False)
    duration_seconds = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=False, default=ConversationStatus.COMPLETED)
    ended_reason = serializers.CharField(required=False, allow_blank=True, default='')
    metrics = serializers.DictField(required=False, default=dict)

    def to_dto(self) -> MistralConversationEndedPayload:
        data = self.validated_data
        return MistralConversationEndedPayload(
            session_id=data['session_id'],
            transcript=[
                TranscriptMessage(
                    role=message['role'],
                    message=message['message'],
                    time_in_call_secs=message.get('time_in_call_secs', 0.0),
                )
                for message in data.get('transcript', [])
            ],
            duration_seconds=data.get('duration_seconds'),
            status=data.get('status', ConversationStatus.COMPLETED),
            ended_reason=data.get('ended_reason', ''),
            metrics=data.get('metrics', {}),
        )


class MistralConversationStartedSerializer(serializers.Serializer):
    """Serializer for the Mistral voice runtime start callback."""

    session_id = serializers.CharField()


class VoiceSerializer(serializers.Serializer):
    """Serializer for ElevenLabs voice list."""
    voice_id = serializers.CharField()
    name = serializers.CharField()
    preview_url = serializers.CharField(required=False, allow_null=True)
    category = serializers.CharField(required=False, allow_null=True)


def _validate_agent_access_code(value, owner, current=None):
    """A voice code must be usable for sign-up, so it is refused when it already
    names a bot code, another creator's assignment, or any other DARE
    registration code. A code the agent already has is accepted as is."""
    code = normalize_voice_access_code(value)
    if not code:
        return code
    if SubscriptionCode.objects.filter(code=code).exists():
        raise serializers.ValidationError(
            "This code is already used by a chat bot access code. Choose a different code."
        )
    if live_agents_for_code(code).exclude(user=owner).exists():
        raise serializers.ValidationError(
            "This code is already used by another instructor's voice assignment. Choose a different code."
        )
    if code != normalize_voice_access_code(current):
        try:
            reserve_agent_code_in_dare(code)
        except VoiceAccessCodeError as exc:
            raise serializers.ValidationError(str(exc))
    return code


def _validate_provider_fields(attrs, instance=None):
    provider = attrs.get(
        'voice_provider',
        getattr(instance, 'voice_provider', VoiceProvider.ELEVENLABS),
    )
    language = attrs.get('language', getattr(instance, 'language', 'en'))

    if provider == VoiceProvider.MISTRAL_VOICE and language not in MISTRAL_SUPPORTED_LANGUAGES:
        supported = ', '.join(sorted(MISTRAL_SUPPORTED_LANGUAGES.keys()))
        raise serializers.ValidationError(
            {"language": f"Mistral Voice supports only: {supported}"}
        )

    llm_model = attrs.get('llm_model', '')
    if llm_model and llm_model not in VOICE_BRAIN_MODEL_IDS:
        raise serializers.ValidationError(
            {"llm_model": "Unknown brain model; pick one from /api/voice/brain-models/"}
        )

    return attrs
