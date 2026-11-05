"""Check with DARE that a bot's owner may save the models a request sets."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

from rest_framework.exceptions import ValidationError

from utils.dare_api import models_client
from utils.dare_api.base import DareApiError
from utils.dare_api.models import BotModelCheckResult

from .constants import MODEL_CHECK_UNAVAILABLE, MODEL_PREFERENCE_FIELDS, MODEL_PROBLEM_MESSAGES
from .models import Bot, BotModelPreference

logger = logging.getLogger(__name__)


def _field_errors(result: BotModelCheckResult) -> dict[str, list[str]]:
    problems = {
        'chat_model_dare_id': result.chat_model_problem,
        'tracking_model_dare_id': result.tracking_model_problem,
    }
    return {
        field: [str(MODEL_PROBLEM_MESSAGES.get(code, MODEL_CHECK_UNAVAILABLE))]
        for field, code in problems.items()
        if code
    }


class BotModelCheckService:
    """Reject models the owner can't use before a bot is saved."""

    @staticmethod
    def check(owner_dare_user_id: int, data: Mapping, bot: Optional[Bot] = None) -> None:
        """Raise ``ValidationError`` for any model in ``data`` the owner can't save.

        Only models that change are checked, so an unrelated edit never fails
        on a bot saved before these checks existed.
        """
        current = BotModelPreference.objects.filter(bot=bot).first() if bot else None
        changed = {
            field: data[field]
            for field in MODEL_PREFERENCE_FIELDS
            if data.get(field) and data[field] != getattr(current, field, None)
        }
        if not changed:
            return
        try:
            result = models_client.check_bot_models(
                owner_dare_user_id,
                changed.get('chat_model_dare_id'),
                changed.get('tracking_model_dare_id'),
            )
        except DareApiError as error:
            logger.error("Could not verify bot models with DARE: %s", error)
            raise ValidationError({field: [MODEL_CHECK_UNAVAILABLE] for field in changed})
        errors = _field_errors(result)
        if errors:
            raise ValidationError(errors)
