import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from bots.models import BotGroup, Bot

User = get_user_model()

class Timestamp(models.Model):
    """Abstract base class for timestamp fields"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class SubscriptionCode(Timestamp):
    """
    Subscription codes for students to access specific bots or bot groups.
    Role assignment is handled by DARE - this model only controls content access.
    """
    code = models.CharField(max_length=255, unique=True)
    bot_group = models.ForeignKey(BotGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='subscription_codes')
    bot = models.ForeignKey(Bot, null=True, blank=True, on_delete=models.CASCADE, related_name='subscription_codes')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_subscription_codes')
    limit = models.IntegerField(
        default=0,
        help_text="Maximum number of times this code can be redeemed."
    )

    def clean(self):
        """Ensure proper validation: subscription codes must be tied to a bot_group or bot"""
        if self.limit is not None and self.limit < 0:
            raise ValidationError("Subscription code limit cannot be negative")
        # Subscription codes must be tied to either a bot_group or bot, but not both
        if not self.bot_group and not self.bot:
            raise ValidationError("Subscription codes must be tied to either a bot group or bot")
        if self.bot_group and self.bot:
            raise ValidationError("Subscription codes cannot be tied to both bot group and bot")

    def save(self, *args, **kwargs):
        # Run clean validation before saving
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.bot_group:
            target = getattr(self.bot_group, 'title', 'Unknown Bot Group')
        elif self.bot:
            target = getattr(self.bot, 'title', 'Unknown Bot')
        else:
            target = "Unknown"
        return f"Subscription Code {self.code} for {target}"

    class Meta:
        ordering = ['-created_at']
        # Keep the existing database table name for backwards compatibility
        db_table = 'access_codes_accesscode'
        verbose_name = "Subscription Code"
        verbose_name_plural = "Subscription Codes"

class SubscriptionCodeAcceptance(Timestamp):
    """
    Tracks which users redeemed which subscription codes and when.
    """
    subscription_code = models.ForeignKey(SubscriptionCode, on_delete=models.CASCADE, related_name='acceptances')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscription_code_acceptances')

    class Meta:
        unique_together = ("subscription_code", "user")
        ordering = ['-created_at']
        # Keep the existing database table name for backwards compatibility
        db_table = 'access_codes_accesscodeacceptance'
        verbose_name = "Subscription Code Acceptance"
        verbose_name_plural = "Subscription Code Acceptances"

    def __str__(self):
        user_name = getattr(self.user, 'email', 'Unknown User')
        code = getattr(self.subscription_code, 'code', 'Unknown Code')
        return f"{user_name} redeemed {code}"

class BotGroupSchedule(Timestamp):
    """
    Defines when bots in a bot group become available.
    """
    bot_group = models.ForeignKey(BotGroup, on_delete=models.CASCADE, related_name="schedules")
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="schedules")
    unlock_date = models.DateTimeField()

    class Meta:
        unique_together = ("bot_group", "bot")
        ordering = ["unlock_date"]

    def __str__(self):
        bot_group_title = getattr(self.bot_group, 'title', 'Unknown Bot Group')
        bot_title = getattr(self.bot, 'title', 'Unknown Bot')
        return f"{bot_group_title} → {bot_title} unlocks at {self.unlock_date}"
