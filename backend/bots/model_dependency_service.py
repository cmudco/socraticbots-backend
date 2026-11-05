"""Lifecycle operations for DARE models referenced by Socratic bots.

A bot stores picker ids: a DARE model's PK (``"42"``) or a LiteLLM route
(``"litellm:<key_id>:<model>"``). Deleting a DARE model clears the exact id;
deleting a LiteLLM key clears every model routed through it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.db.models import Q, QuerySet

from .models import Bot, BotModelPreference


@dataclass(frozen=True)
class ModelReference:
    """Which stored picker ids a lifecycle operation targets."""

    exact: Optional[str] = None
    prefix: Optional[str] = None

    @classmethod
    def dare_model(cls, model_id: int) -> "ModelReference":
        return cls(exact=str(model_id))

    @classmethod
    def litellm_key(cls, key_id: str) -> "ModelReference":
        return cls(prefix=f"litellm:{key_id}:")

    def filter_for(self, field: str) -> Q:
        if self.exact is not None:
            return Q(**{field: self.exact})
        return Q(**{f"{field}__startswith": self.prefix})

    def matches(self, value: Optional[str]) -> bool:
        if value is None:
            return False
        if self.exact is not None:
            return value == self.exact
        return value.startswith(self.prefix)


@dataclass(frozen=True)
class BotModelDependency:
    bot_id: int
    bot_title: str
    bot_group_id: int
    bot_group_title: str
    subject: str
    usage_type: str
    owner_email: str
    owner_dare_id: Optional[int]

    def to_dict(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "bot_title": self.bot_title,
            "bot_group_id": self.bot_group_id,
            "bot_group_title": self.bot_group_title,
            "subject": self.subject,
            "usage_type": self.usage_type,
            "owner_email": self.owner_email,
            "owner_dare_id": self.owner_dare_id,
        }


@dataclass(frozen=True)
class BotModelDependencySnapshot:
    model_id: int
    bots: tuple[BotModelDependency, ...]

    def to_dict(self) -> dict:
        return {
            "dare_model_id": self.model_id,
            "dependent_bots_count": len(self.bots),
            "dependent_bots": [bot.to_dict() for bot in self.bots],
        }


@dataclass(frozen=True)
class BotModelNullificationResult:
    model_id: Optional[int]
    affected_bots_count: int
    affected_owner_dare_ids: tuple[int, ...]

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "affected_bots_count": self.affected_bots_count,
            "affected_owner_dare_ids": list(self.affected_owner_dare_ids),
        }


class BotModelDependencyService:
    """Find and clear Socratic bot references to a DARE model or LiteLLM key."""

    @classmethod
    def preview(cls, model_id: int) -> BotModelDependencySnapshot:
        return BotModelDependencySnapshot(
            model_id=model_id,
            bots=cls.dependencies(ModelReference.dare_model(model_id)),
        )

    @classmethod
    def nullify(cls, model_id: int) -> BotModelNullificationResult:
        return cls.clear(ModelReference.dare_model(model_id), model_id=model_id)

    @classmethod
    def dependencies(cls, reference: ModelReference) -> tuple[BotModelDependency, ...]:
        return cls._dependencies_from_preferences(
            cls._preferences_for(reference), reference
        )

    @classmethod
    def clear(
        cls, reference: ModelReference, *, model_id: Optional[int] = None
    ) -> BotModelNullificationResult:
        """Clear both model fields and deactivate every affected bot atomically."""
        with transaction.atomic():
            preferences = cls._preferences_for(reference).select_for_update()
            dependencies = cls._dependencies_from_preferences(preferences, reference)
            affected_bot_ids = {dependency.bot_id for dependency in dependencies}
            owner_ids = sorted(
                {
                    dependency.owner_dare_id
                    for dependency in dependencies
                    if dependency.owner_dare_id is not None
                }
            )

            BotModelPreference.objects.filter(
                reference.filter_for("chat_model_dare_id")
            ).update(chat_model_dare_id=None)
            BotModelPreference.objects.filter(
                reference.filter_for("tracking_model_dare_id")
            ).update(tracking_model_dare_id=None)
            if affected_bot_ids:
                Bot.objects.filter(pk__in=affected_bot_ids).update(is_active=False)

        return BotModelNullificationResult(
            model_id=model_id,
            affected_bots_count=len(affected_bot_ids),
            affected_owner_dare_ids=tuple(owner_ids),
        )

    @staticmethod
    def _preferences_for(reference: ModelReference) -> QuerySet[BotModelPreference]:
        return BotModelPreference.objects.filter(
            reference.filter_for("chat_model_dare_id")
            | reference.filter_for("tracking_model_dare_id")
        ).select_related("bot", "bot__bot_group", "bot__user")

    @staticmethod
    def _dependencies_from_preferences(
        preferences: QuerySet[BotModelPreference],
        reference: ModelReference,
    ) -> tuple[BotModelDependency, ...]:
        dependencies = []
        for preference in preferences:
            usages = []
            if reference.matches(preference.chat_model_dare_id):
                usages.append("chat")
            if reference.matches(preference.tracking_model_dare_id):
                usages.append("tracking")

            bot = preference.bot
            dependencies.append(
                BotModelDependency(
                    bot_id=bot.pk,
                    bot_title=bot.title,
                    bot_group_id=bot.bot_group_id,
                    bot_group_title=bot.bot_group.title,
                    subject=bot.subject,
                    usage_type=" and ".join(usages),
                    owner_email=bot.user.email,
                    owner_dare_id=bot.user.external_user_id,
                )
            )
        return tuple(dependencies)
