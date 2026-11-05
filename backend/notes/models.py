# notes/models.py
import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Note(models.Model):
    # Internal ID is automatic (Django will create it)
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # Bot relationship - notes are bot-specific
    bot = models.ForeignKey(
        'bots.Bot',
        on_delete=models.CASCADE,
        related_name='notes'
    )

    # Basic required fields
    title = models.CharField(max_length=255)
    content = models.TextField()

    # User relationship (derived from bot.user, but kept for easy querying)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notes')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']  # Newest first
        indexes = [
            models.Index(fields=['bot', 'user']),
        ]

    def __str__(self):
        return f"{self.title} - {self.bot.title}"

    def save(self, *args, **kwargs):
        # Ensure user matches bot.user for data consistency
        if self.bot_id and not self.user_id:
            self.user = self.bot.user
        super().save(*args, **kwargs)
