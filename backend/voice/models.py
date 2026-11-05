# voice/models.py
"""
Models for ElevenLabs Voice Agent integration.
"""

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

from voice.constants import (
    VoiceAgentStatus, ConversationStatus,
    VoiceTeamRole, VoiceAgentRole, VoiceProvider,
    VoiceEagerness, DEFAULT_TEMPERATURE, DEFAULT_MAX_DURATION,
    DEFAULT_VOICE_TURN_TIMEOUT_SECS,
)


class VoiceTeam(models.Model):
    """
    A teaching team that owns voice agents.
    Provisioned by DARE Sys Admin via Django Admin.
    """
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_voice_teams',
        help_text="DARE Sys Admin who provisioned this team"
    )
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def soft_delete(self):
        self.is_deleted = True
        self.is_active = False
        self.save(update_fields=['is_deleted', 'is_active'])


class VoiceAgent(models.Model):
    """
    Model for ElevenLabs Conversational AI agents.
    Stores configuration and links to ElevenLabs agent_id.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_agents',
        help_text="User who owns this agent"
    )
    name = models.CharField(
        max_length=255,
        help_text="Display name for the agent"
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text="Description of the agent's purpose"
    )
    team = models.ForeignKey(
        VoiceTeam,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='agents',
        help_text="Team this agent belongs to (null for legacy agents)"
    )

    # ElevenLabs Configuration
    elevenlabs_agent_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="ElevenLabs agent ID (set after creation via API)"
    )
    voice_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="ElevenLabs voice ID to use"
    )
    voice_provider = models.CharField(
        max_length=30,
        choices=VoiceProvider.choices,
        default=VoiceProvider.MISTRAL_VOICE,
        help_text="Voice runtime/provider for this agent"
    )
    language = models.CharField(
        max_length=10,
        default='en',
        help_text="Language code for provider speech/STT/TTS configuration"
    )

    # Agent Configuration
    system_prompt = models.TextField(
        help_text="System prompt / instructions for the agent"
    )
    first_message = models.TextField(
        blank=True,
        default='',
        help_text="Initial greeting message from the agent"
    )
    temperature = models.FloatField(
        default=DEFAULT_TEMPERATURE,
        validators=[MinValueValidator(0.0), MaxValueValidator(2.0)],
        help_text="LLM temperature setting"
    )
    max_duration_seconds = models.PositiveIntegerField(
        default=DEFAULT_MAX_DURATION,
        help_text="Maximum conversation duration in seconds"
    )

    # Mistral-side advanced knobs. Currently consumed only by the Pipecat
    # runtime; ElevenLabs ignores them (its own knobs live in
    # ``conversation_config``).
    voice_eagerness = models.CharField(
        max_length=10,
        choices=VoiceEagerness.choices,
        default=VoiceEagerness.NORMAL,
        help_text="How quickly the agent jumps in after the student pauses"
    )
    voice_turn_timeout_secs = models.PositiveIntegerField(
        default=DEFAULT_VOICE_TURN_TIMEOUT_SECS,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="Max silence (seconds) before the agent prompts the student"
    )
    llm_model = models.CharField(
        max_length=100,
        blank=True,
        default='gemini-3.1-flash-lite',
        help_text="Brain model id (see VOICE_BRAIN_MODELS)"
    )

    # Full ElevenLabs conversation_config (for advanced settings)
    # Stores: turn, tts, conversation, agent settings
    conversation_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full ElevenLabs conversation_config JSON"
    )

    # Exam Configuration
    exam_title = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Title of the exam"
    )
    exam_instructions = models.TextField(
        blank=True,
        default='',
        help_text="Instructions shown to users before starting"
    )
    default_max_attempts = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Maximum attempts assigned to students when they first unlock this agent"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=VoiceAgentStatus.choices,
        default=VoiceAgentStatus.DRAFT,
        help_text="Agent status (active = accessible to all users)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Student access code
    access_code = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Code students enter to unlock this exam"
    )

    # Soft delete flag
    is_deleted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['elevenlabs_agent_id']),
            models.Index(fields=['voice_provider'], name='voice_voice_voice_p_f1c7ab_idx'),
            models.Index(fields=['status']),
            models.Index(fields=['team', 'status']),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.email})"

    def soft_delete(self):
        """Soft delete the agent."""
        self.is_deleted = True
        self.is_active = False
        self.save(update_fields=['is_deleted', 'is_active'])


class VoiceAgentAccess(models.Model):
    """
    Tracks which students have unlocked a VoiceAgent via access code.
    """
    agent = models.ForeignKey(
        VoiceAgent,
        on_delete=models.CASCADE,
        related_name='student_accesses'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_agent_accesses'
    )
    max_attempts = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Maximum number of attempts allowed for this student"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('agent', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} -> {self.agent.name}"


class VoiceTeamMembership(models.Model):
    """
    Group-level role assignment. Role applies to ALL agents in the team.
    Roles: manager, admin (future Co-Admin), reviewer.
    """
    team = models.ForeignKey(
        VoiceTeam,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_team_memberships'
    )
    role = models.CharField(
        max_length=20,
        choices=VoiceTeamRole.choices,
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='granted_team_memberships',
        help_text="User who granted this membership"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('team', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} → {self.team.name} ({self.role})"


class VoiceAgentMembership(models.Model):
    """
    Bot-level role assignment. Role applies to ONE specific agent.
    Roles: admin (future Co-Admin), reviewer.
    """
    agent = models.ForeignKey(
        VoiceAgent,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_agent_memberships'
    )
    role = models.CharField(
        max_length=20,
        choices=VoiceAgentRole.choices,
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='granted_agent_memberships',
        help_text="User who granted this membership"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('agent', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} → {self.agent.name} ({self.role})"


class VoiceConversation(models.Model):
    """
    Model for storing voice conversation sessions.
    Records each user's exam attempt with transcript.
    """
    agent = models.ForeignKey(
        VoiceAgent,
        on_delete=models.CASCADE,
        related_name='conversations'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_conversations'
    )

    # ElevenLabs Session
    elevenlabs_conversation_id = models.CharField(
        max_length=100,
        unique=True,
        help_text="ElevenLabs conversation ID"
    )
    provider_conversation_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Generic provider/runtime conversation ID"
    )

    # Session Metadata
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the conversation started"
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the conversation ended"
    )
    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total duration in seconds"
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=ConversationStatus.choices,
        default=ConversationStatus.IN_PROGRESS
    )

    # Transcript stored as JSON
    transcript = models.JSONField(
        default=list,
        blank=True,
        help_text="Full conversation transcript"
    )

    # FERPA Compliance
    elevenlabs_deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the conversation was deleted from ElevenLabs servers"
    )
    compliance_receipt = models.JSONField(
        default=dict,
        blank=True,
        help_text="FERPA compliance receipt (conversationId, storedInSbAt, deletedFromElevenLabs, etc.)"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    # Soft delete flag
    is_deleted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['agent', 'user']),
            models.Index(fields=['elevenlabs_conversation_id']),
            models.Index(fields=['provider_conversation_id'], name='voice_voice_provide_4c44f6_idx'),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Conversation {self.elevenlabs_conversation_id} - {self.user.email}"


class VoiceBrowserDiagnostic(models.Model):
    """Browser-reported evidence, not a root-cause verdict or an exam attempt."""

    attempt_id = models.UUIDField(primary_key=True)
    agent = models.ForeignKey(VoiceAgent, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.OneToOneField(
        VoiceConversation, on_delete=models.CASCADE, null=True, blank=True,
        related_name='browser_diagnostic',
    )
    events = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
