# voice/api/urls.py
"""
URL configuration for Voice API.
"""

from django.urls import path, include

from rest_framework.routers import DefaultRouter

from .lab_views import start_stt_lab_session
from .views import VoiceAgentViewSet, VoiceConversationViewSet
from .voice_catalog_views import brain_models, mistral_voices
from .webhook_views import elevenlabs_webhook
from .runtime_views import (
    voice_runtime_conversation_ended,
    voice_runtime_conversation_started,
    voice_runtime_session_context,
)

router = DefaultRouter()
router.register(r'agents', VoiceAgentViewSet, basename='voice-agent')
router.register(r'conversations', VoiceConversationViewSet, basename='voice-conversation')

urlpatterns = [
    path('', include(router.urls)),
    path('mistral-voices/', mistral_voices, name='mistral-voices'),
    path('brain-models/', brain_models, name='brain-models'),
    path('lab/session/', start_stt_lab_session, name='voice-lab-session'),
    path('webhook/elevenlabs/', elevenlabs_webhook, name='elevenlabs-webhook'),
    path(
        'runtime/conversation-started/',
        voice_runtime_conversation_started,
        name='voice-runtime-conversation-started',
    ),
    path(
        'runtime/conversation-ended/',
        voice_runtime_conversation_ended,
        name='voice-runtime-conversation-ended',
    ),
    path(
        'runtime/sessions/<str:session_id>/context/',
        voice_runtime_session_context,
        name='voice-runtime-session-context',
    ),
]
