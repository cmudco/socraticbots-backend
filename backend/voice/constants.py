# voice/constants.py
"""
Voice app constants for ElevenLabs integration.
"""

from django.db import models

APP_NAME = "voice"


class VoiceAgentStatus(models.TextChoices):
    """Status choices for VoiceAgent."""
    DRAFT = 'draft', 'Draft'
    ACTIVE = 'active', 'Active'


class ConversationStatus(models.TextChoices):
    """Status choices for VoiceConversation."""
    RESERVED = 'reserved', 'Reserved'
    IN_PROGRESS = 'in_progress', 'In Progress'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class VoiceProvider(models.TextChoices):
    """Voice runtime/provider choices."""
    ELEVENLABS = 'elevenlabs', 'ElevenLabs'
    # Mistral Voxtral via the full-duplex Pipecat runtime
    # (server-side VAD + barge-in + streaming).
    MISTRAL_VOICE = 'mistral_pipecat', 'Mistral Voice'


class VoiceEagerness(models.TextChoices):
    """How quickly the voice agent jumps in after the student pauses.

    Maps at runtime to Silero VAD ``stop_secs``: smaller = more eager,
    larger = more patient. The mapping lives in the voice runtime, not in
    Django, so the model doesn't depend on VAD specifics.
    """
    LOW = 'low', 'Low (patient — waits longer before responding)'
    NORMAL = 'normal', 'Normal'
    HIGH = 'high', 'High (snappy — jumps in quickly)'


DEFAULT_VOICE_TURN_TIMEOUT_SECS = 7

# Brain (LLM) models a Mistral Voice agent can run on. The voice runtime
# resolves the provider from the id and fails over to the next configured
# model if the chosen one stalls, so the student never waits on one vendor.
# llm_model defaults to Gemini 3.1 Flash Lite (fastest/smoothest in QA);
# existing agents were backfilled to it by migration 0011.
VOICE_BRAIN_MODELS = [
    {
        'id': 'gemini-3.1-flash-lite',
        'label': 'Gemini 3.1 Flash Lite',
        'provider': 'Google',
        'description': 'Default. Fast and smooth in live exams.',
    },
    {
        'id': 'gpt-5.6-luna',
        'label': 'GPT-5.6 Luna',
        'provider': 'OpenAI',
        'description': 'Cheap, fast OpenAI model.',
    },
    {
        'id': 'claude-haiku-4-5-20251001',
        'label': 'Claude Haiku 4.5',
        'provider': 'Anthropic',
        'description': 'Cheap, fast Anthropic model.',
    },
    {
        'id': 'mistral-large-latest',
        'label': 'Mistral Large',
        'provider': 'Mistral',
        'description': 'Strongest Mistral model (previous default).',
    },
    {
        'id': 'mistral-small-latest',
        'label': 'Mistral Small',
        'provider': 'Mistral',
        'description': 'Cheaper and faster Mistral model.',
    },
]
VOICE_BRAIN_MODEL_IDS = {m['id'] for m in VOICE_BRAIN_MODELS}


# English Kokoro voices graded C or better in Kokoro's VOICES.md, best first per
# group. The runtime keeps the same ids and ignores anything else in voice_id.
KOKORO_VOICES = [
    {'id': 'af_heart', 'label': 'Heart', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_bella', 'label': 'Bella', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_nicole', 'label': 'Nicole', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_aoede', 'label': 'Aoede', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_kore', 'label': 'Kore', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_sarah', 'label': 'Sarah', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_alloy', 'label': 'Alloy', 'gender': 'Female', 'accent': 'American'},
    {'id': 'af_nova', 'label': 'Nova', 'gender': 'Female', 'accent': 'American'},
    {'id': 'bf_emma', 'label': 'Emma', 'gender': 'Female', 'accent': 'British'},
    {'id': 'bf_isabella', 'label': 'Isabella', 'gender': 'Female', 'accent': 'British'},
    {'id': 'am_fenrir', 'label': 'Fenrir', 'gender': 'Male', 'accent': 'American'},
    {'id': 'am_michael', 'label': 'Michael', 'gender': 'Male', 'accent': 'American'},
    {'id': 'am_puck', 'label': 'Puck', 'gender': 'Male', 'accent': 'American'},
    {'id': 'bm_george', 'label': 'George', 'gender': 'Male', 'accent': 'British'},
    {'id': 'bm_fable', 'label': 'Fable', 'gender': 'Male', 'accent': 'British'},
]


class VoiceTeamRole(models.TextChoices):
    """Team-level roles. Manager and Reviewer are active use cases;
    Admin is reserved for future Co-Admin capability."""
    MANAGER = 'manager', 'Manager'
    ADMIN = 'admin', 'Admin'
    REVIEWER = 'reviewer', 'Reviewer'


class VoiceAgentRole(models.TextChoices):
    """Bot-level delegated roles. Reserved for future per-bot delegation."""
    ADMIN = 'admin', 'Admin'
    REVIEWER = 'reviewer', 'Reviewer'


# Role priority used by access resolver (higher number = higher privilege)
ROLE_PRIORITY = {
    'reviewer': 1,
    'admin': 2,
    'manager': 3,
}


# ElevenLabs API endpoints
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_AGENTS_BASE = f"{ELEVENLABS_API_BASE}/convai/agents"
ELEVENLABS_AGENTS_CREATE_ENDPOINT = f"{ELEVENLABS_AGENTS_BASE}/create"
ELEVENLABS_SIGNED_URL_ENDPOINT = f"{ELEVENLABS_API_BASE}/convai/conversation/get_signed_url"
ELEVENLABS_CONVERSATION_ENDPOINT = f"{ELEVENLABS_API_BASE}/convai/conversations"
ELEVENLABS_VOICES_ENDPOINT = f"{ELEVENLABS_API_BASE}/voices"

# Default agent settings
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_DURATION = 1800  # 30 minutes in seconds

# Mistral Voice rollout language support. Keep parity with the current
# ElevenLabs exam setup: English only.
MISTRAL_SUPPORTED_LANGUAGES = {
    'en': 'English',
}

VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS = 5 * 60

# Webhook constants
ELEVENLABS_WEBHOOK_SIGNATURE_HEADER = "ElevenLabs-Signature"
ELEVENLABS_WEBHOOK_EVENTS = ["transcript"]  # Events to subscribe to

# Agent naming convention separator
# ElevenLabs agents are named: <email_prefix>__<agent_name>
# e.g., "farhat.abbas3500__MyExamAgent"
AGENT_NAME_SEPARATOR = "__"


def get_email_prefix(email: str) -> str:
    """Extract the part before @ from an email address."""
    return email.split("@")[0]


def build_elevenlabs_agent_name(email: str, display_name: str) -> str:
    """Build the ElevenLabs agent name with email prefix convention."""
    prefix = get_email_prefix(email)
    return f"{prefix}{AGENT_NAME_SEPARATOR}{display_name}"


def parse_elevenlabs_agent_name(elevenlabs_name: str) -> str:
    """Extract the display name from an ElevenLabs agent name.

    Returns the part after the separator, or the full name if no separator found.
    """
    if AGENT_NAME_SEPARATOR in elevenlabs_name:
        return elevenlabs_name.split(AGENT_NAME_SEPARATOR, 1)[1]
    return elevenlabs_name


def agent_belongs_to_user(elevenlabs_name: str, email: str) -> bool:
    """Check if an ElevenLabs agent name belongs to a given user."""
    prefix = get_email_prefix(email)
    return elevenlabs_name.startswith(f"{prefix}{AGENT_NAME_SEPARATOR}")
