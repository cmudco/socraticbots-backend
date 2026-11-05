"""Keep bounded client evidence separate from authoritative session outcomes."""
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.throttling import UserRateThrottle

from voice.models import VoiceBrowserDiagnostic, VoiceConversation


class BrowserDiagnosticThrottle(UserRateThrottle):
    scope = 'voice_browser_diagnostics'
    rate = '60/min'


class BrowserEventSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(min_value=0, max_value=100000)
    elapsed_ms = serializers.IntegerField(min_value=0, max_value=86400000)
    stage = serializers.ChoiceField(choices=['microphone', 'reservation', 'connection', 'active', 'ending'])
    kind = serializers.ChoiceField(choices=[
        'network_offline', 'network_online', 'microphone_ready', 'microphone_error',
        'microphone_muted', 'microphone_unmuted', 'microphone_ended',
        'peer_state', 'start_failed', 'client_end',
    ])
    online = serializers.BooleanField()
    error_name = serializers.ChoiceField(required=False, choices=[
        'NotAllowedError', 'NotFoundError', 'NotReadableError', 'OverconstrainedError',
        'SecurityError', 'AbortError', 'TypeError', 'Error', 'OtherError',
    ])
    peer_state = serializers.ChoiceField(required=False, choices=[
        'new', 'connecting', 'connected', 'disconnected', 'failed', 'closed',
    ])


class BrowserDiagnosticSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    conversation_id = serializers.CharField(required=False, max_length=100)
    events = BrowserEventSerializer(many=True, allow_empty=False, max_length=64)


@transaction.atomic
def save_browser_diagnostic(*, agent, user, data) -> None:
    conversation = None
    if data.get('conversation_id'):
        # Lock the conversation too: only one browser attempt may be associated.
        conversation = VoiceConversation.objects.select_for_update().filter(
            Q(provider_conversation_id=data['conversation_id']) |
            Q(elevenlabs_conversation_id=data['conversation_id']),
            agent=agent, user=user, is_deleted=False,
        ).first()
        if not conversation:
            raise PermissionDenied('Conversation not available.')
        if VoiceBrowserDiagnostic.objects.filter(conversation=conversation).exclude(
            attempt_id=data['attempt_id'],
        ).exists():
            raise serializers.ValidationError('Conversation already has browser evidence.')

    diagnostic, _ = VoiceBrowserDiagnostic.objects.get_or_create(
        attempt_id=data['attempt_id'], defaults={'agent': agent, 'user': user},
    )
    diagnostic = VoiceBrowserDiagnostic.objects.select_for_update().get(pk=diagnostic.pk)
    if diagnostic.user_id != user.pk or diagnostic.agent_id != agent.pk:
        raise PermissionDenied('Attempt not available.')
    if conversation:
        if diagnostic.conversation_id and diagnostic.conversation_id != conversation.pk:
            raise serializers.ValidationError('Attempt already linked to another conversation.')
        diagnostic.conversation = conversation

    # First received value wins for duplicate sequence numbers; late batches cannot erase events.
    events = {event['sequence']: event for event in diagnostic.events}
    for event in data['events']:
        events.setdefault(event['sequence'], dict(event))
    diagnostic.events = [events[key] for key in sorted(events)[-64:]]
    diagnostic.save(update_fields=['conversation', 'events', 'updated_at'])
