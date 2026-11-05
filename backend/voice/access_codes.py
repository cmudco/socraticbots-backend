"""
Voice-assignment access codes as a sign-up credential.

A voice agent's ``access_code`` unlocks the assignment for existing users
(``redeem_access_code``). This module lets the same code also create an
account: the code is mirrored into DARE as a RESEARCHER registration code so
DARE's own registration path assigns the role, and after registration every
live assignment sharing the code (same creator) is unlocked here.

DARE calls fail closed both when a creator saves a code and during
registration (which re-ensures the code, so agents created before this
feature still work).
"""

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from utils.dare_api import DareApiError, auth_client
from voice.models import VoiceAgent, VoiceAgentAccess

logger = logging.getLogger(__name__)

VOICE_PROVISIONER = 'SOCRATIC_VOICE'


class VoiceAccessCodeError(Exception):
    """A code that must not be used for sign-up, with a user-facing message."""


@dataclass(frozen=True)
class VoiceCodeMatch:
    agents: List[VoiceAgent]

    @property
    def creator_id(self) -> int:
        return self.agents[0].user_id


def normalize_voice_access_code(value: Optional[str]) -> str:
    return (value or '').strip()


def live_agents_for_code(code: str) -> QuerySet:
    """Agents a code can unlock: same matching rules as ``redeem_access_code``."""
    code = normalize_voice_access_code(code)
    if not code:
        return VoiceAgent.objects.none()
    return VoiceAgent.objects.filter(access_code=code, is_deleted=False, is_active=True)


def resolve_voice_signup_code(code: str) -> Optional[VoiceCodeMatch]:
    """
    Every live assignment a sign-up code unlocks, or ``None`` if no voice agent
    uses the code. A code shared across creators is refused: there is no way to
    tell which assignment the new user was invited to.
    """
    agents = list(live_agents_for_code(code).order_by('created_at', 'pk'))
    if not agents:
        return None
    if len({agent.user_id for agent in agents}) > 1:
        raise VoiceAccessCodeError(
            "This access code is used by more than one instructor and cannot be used to "
            "sign up. Ask your instructor for a new code."
        )
    return VoiceCodeMatch(agents=agents)


def grant_voice_access(user, agents: Iterable[VoiceAgent]) -> List[VoiceAgentAccess]:
    """Unlock each agent for the user, inheriting the agent's attempt default.
    Idempotent: an existing grant (and any per-student override) is kept."""
    grants = []
    for agent in agents:
        try:
            with transaction.atomic():
                access, _ = VoiceAgentAccess.objects.get_or_create(
                    agent=agent,
                    user=user,
                    defaults={'max_attempts': agent.default_max_attempts},
                )
        except IntegrityError:
            access = VoiceAgentAccess.objects.get(agent=agent, user=user)
        grants.append(access)
    return grants


def ensure_signup_code_in_dare(code: str) -> None:
    """
    Make sure DARE holds the code as a voice-provisioned RESEARCHER registration
    code before a new user registers with it. Fails closed.
    """
    try:
        result = auth_client.provision_voice_access_code(code, action='ensure')
    except DareApiError as exc:
        logger.exception("DARE unavailable while provisioning a voice sign-up code")
        raise VoiceAccessCodeError(
            "The registration service is temporarily unavailable. Please try again in a few minutes."
        ) from exc
    if result.get('conflict'):
        raise VoiceAccessCodeError(
            "This access code cannot be used to sign up because it is already reserved for a "
            "different kind of registration. Ask your instructor for a different code."
        )


def reserve_agent_code_in_dare(code: str) -> None:
    """
    Reserve a code a creator is setting as a voice-provisioned RESEARCHER
    registration code in DARE (re-activating it if this creator used it before).
    Fails closed with a user-facing message: a code DARE already uses for a
    different registration group is refused so the creator learns now, not
    when a student cannot sign up.
    """
    try:
        result = auth_client.provision_voice_access_code(code, action='ensure', activate=True)
    except DareApiError as exc:
        logger.exception("DARE unavailable while reserving a voice access code")
        raise VoiceAccessCodeError(
            "Could not verify this access code with the registration service. Please try again."
        ) from exc
    if result.get('conflict'):
        raise VoiceAccessCodeError(
            "This code is already used by another registration code. Choose a different code."
        )


def release_agent_code_in_dare(code: str) -> None:
    """Best-effort: deactivate the DARE registration code once no live agent uses it."""
    code = normalize_voice_access_code(code)
    if not code or live_agents_for_code(code).exists():
        return
    try:
        auth_client.provision_voice_access_code(code, action='deactivate')
    except DareApiError:
        logger.exception("Could not release a voice access code in DARE")
