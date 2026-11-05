# bots/models.py
from django.db import models
from django.conf import settings


class BotGroup(models.Model):
    """
    Bot Group (formerly Book) - Container for multiple bots
    Simple integer ID, no UUID complexity
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='bot_groups'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='collaborated_bot_groups',
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class Bot(models.Model):
    """
    Bot (formerly Chapter) - Individual AI bot within a group
    Uses DARE file IDs and simple integer ID
    """
    bot_group = models.ForeignKey(BotGroup, on_delete=models.CASCADE, related_name='bots')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bots')
    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    topic = models.CharField(max_length=255)
    dare_file_ids = models.JSONField(default=list, blank=True, help_text="List of DARE file IDs associated with this bot")
    is_advanced = models.BooleanField(default=False)
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this bot is active and available for use"
    )
    web_search_enabled = models.BooleanField(
        default=False,
        help_text="Enable real-time web search for up-to-date information"
    )
    RAG_MODE_CHOICES = [
        ('naive', 'Naive'),
        ('advanced', 'Advanced'),
        ('agentic', 'Agentic'),
    ]
    rag_mode = models.CharField(
        max_length=16,
        choices=RAG_MODE_CHOICES,
        default='advanced',
        help_text=(
            "Retrieval strategy: naive uses direct lookup; advanced uses DARE's "
            "RAG pipeline; agentic searches through tools in authenticated chats. "
            "Public agentic chats use advanced retrieval."
        ),
    )
    max_context_snippets = models.IntegerField(default=12)
    chat_history_limit = models.PositiveIntegerField(
        default=0,
        help_text="Latest messages the bot reads each turn; 0 reads the whole conversation.",
    )
    tracking_history_limit = models.PositiveIntegerField(
        default=0,
        help_text="Latest messages the progress tracker reads; 0 reads the whole conversation.",
    )
    document_similarity_threshold = models.FloatField(default=0.0)
    is_publicly_deployed = models.BooleanField(
        default=False,
        help_text="Whether this bot is accessible publicly without authentication"
    )
    budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Hard ceiling for anonymous public deployment spend on this bot "
            "(in USD). Required when is_publicly_deployed=True."
        ),
    )
    budget_used = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Cumulative anonymous public deployment spend attributed to this bot (in USD).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        # Prevent duplicate bots with same title in same group by same user
        unique_together = ['bot_group', 'title', 'user']

    def __str__(self):
        return f"{self.bot_group.title} - {self.title}"


class BotModelPreference(models.Model):
    """
    AI model preferences for bots using DARE LLM IDs
    """
    bot = models.OneToOneField(
        Bot, 
        on_delete=models.CASCADE, 
        related_name='model_preference'
    )
    # Stored as the opaque picker id from DARE — either a stringified LLM PK
    # (e.g. "42") or a LiteLLM-routed handle (e.g.
    # "litellm:<key_pk>:<model_name>"). DARE's `parse_model_id` decodes this
    # on dispatch, so SB stores it verbatim and never tries to interpret it.
    chat_model_dare_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Opaque DARE model id (LLM PK or 'litellm:<key>:<name>')"
    )
    tracking_model_dare_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Opaque DARE model id (LLM PK or 'litellm:<key>:<name>')"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Model preferences for {self.bot.title}"


class BotPrompt(models.Model):
    """
    Prompts configuration for bots
    """
    bot = models.OneToOneField(
        Bot,
        on_delete=models.CASCADE,
        related_name='prompts'
    )
    greeting = models.TextField(blank=True)
    chat_prompt = models.TextField(blank=True)
    tracking_prompt = models.TextField(blank=True)
    learning_goals = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prompts for {self.bot.title}"


class BotTheme(models.Model):
    """
    Theme customization for bot public chat interface
    """
    FONT_FAMILY_CHOICES = [
        ('sans', 'Sans Serif'),
        ('serif', 'Serif'),
        ('mono', 'Monospace'),
    ]

    FONT_SIZE_CHOICES = [
        ('xs', 'Extra Small'),
        ('sm', 'Small'),
        ('base', 'Base'),
        ('lg', 'Large'),
        ('xl', 'Extra Large'),
    ]

    BORDER_RADIUS_CHOICES = [
        ('none', 'None'),
        ('sm', 'Small'),
        ('md', 'Medium'),
        ('lg', 'Large'),
        ('xl', 'Extra Large'),
    ]

    MESSAGE_SPACING_CHOICES = [
        ('compact', 'Compact'),
        ('normal', 'Normal'),
        ('relaxed', 'Relaxed'),
    ]

    bot = models.OneToOneField(
        Bot,
        on_delete=models.CASCADE,
        related_name='theme'
    )
    primary_color = models.CharField(
        max_length=7,
        default='#8b5cf6',
        help_text="Primary color in hex format (e.g., #8b5cf6)"
    )
    accent_color = models.CharField(
        max_length=7,
        default='#a78bfa',
        help_text="Accent color in hex format (e.g., #a78bfa)"
    )
    background_color = models.CharField(
        max_length=7,
        default='#ffffff',
        help_text="Background color in hex format (e.g., #ffffff)"
    )
    foreground_color = models.CharField(
        max_length=7,
        default='#0f172a',
        help_text="Foreground/text color in hex format (e.g., #0f172a)"
    )
    font_family = models.CharField(
        max_length=10,
        choices=FONT_FAMILY_CHOICES,
        default='sans',
        help_text="Font family for bot chat interface"
    )
    font_size = models.CharField(
        max_length=10,
        choices=FONT_SIZE_CHOICES,
        default='base',
        help_text="Base font size for bot chat interface"
    )
    border_radius = models.CharField(
        max_length=10,
        choices=BORDER_RADIUS_CHOICES,
        default='md',
        help_text="Border radius for chat elements"
    )
    message_spacing = models.CharField(
        max_length=10,
        choices=MESSAGE_SPACING_CHOICES,
        default='normal',
        help_text="Spacing between messages"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Theme for {self.bot.title}"


class BotQuickPrompt(models.Model):
    """
    Quick prompt template for bots - displayed as pills above chat input
    Users can click on a pill to populate the chat input with the prompt text
    """
    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name='quick_prompts'
    )
    title = models.CharField(
        max_length=100,
        help_text="Short label displayed on the pill button"
    )
    prompt = models.TextField(
        help_text="Full prompt text inserted into chat input when clicked"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order (ascending)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"Quick prompt '{self.title}' for {self.bot.title}"
