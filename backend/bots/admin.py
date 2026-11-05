# bots/admin.py
from django.contrib import admin
from .models import BotGroup, Bot, BotModelPreference, BotPrompt, BotTheme


class BotInline(admin.TabularInline):
    model = Bot
    extra = 0
    fields = ('title', 'subject', 'topic', 'user')
    readonly_fields = ('id',)


@admin.register(BotGroup)
class BotGroupAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'owner', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('title', 'description', 'owner__email')
    readonly_fields = ('id', 'created_at', 'updated_at')
    filter_horizontal = ('collaborators',)
    inlines = [BotInline]
    
    fieldsets = (
        (None, {
            'fields': ('title', 'description', 'owner')
        }),
        ('Collaboration', {
            'fields': ('collaborators',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


class BotModelPreferenceInline(admin.StackedInline):
    model = BotModelPreference
    extra = 0


class BotPromptInline(admin.StackedInline):
    model = BotPrompt
    extra = 0


class BotThemeInline(admin.StackedInline):
    model = BotTheme
    extra = 0


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'bot_group', 'user', 'subject', 'is_advanced', 'files_count', 'created_at')
    list_filter = ('bot_group', 'subject', 'created_at', 'updated_at')
    search_fields = ('title', 'subject', 'topic', 'user__email', 'bot_group__title')
    readonly_fields = ('id', 'created_at', 'updated_at', 'files_count')
    inlines = [BotModelPreferenceInline, BotPromptInline, BotThemeInline]
    
    fieldsets = (
        (None, {
            'fields': ('title', 'bot_group', 'user')
        }),
        ('Content', {
            'fields': ('subject', 'topic', 'is_advanced')
        }),
        ('DARE Integration', {
            'fields': ('dare_file_ids', 'files_count'),
            'description': 'Files are managed through DARE backend'
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def files_count(self, obj):
        return len(obj.dare_file_ids) if obj.dare_file_ids else 0
    files_count.short_description = 'Files Count'


@admin.register(BotModelPreference)
class BotModelPreferenceAdmin(admin.ModelAdmin):
    list_display = ('id', 'bot', 'chat_model_dare_id', 'tracking_model_dare_id', 'created_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('bot__title', 'bot__bot_group__title')
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        (None, {
            'fields': ('bot',)
        }),
        ('DARE LLM Models', {
            'fields': ('chat_model_dare_id', 'tracking_model_dare_id'),
            'description': 'References to DARE backend LLM model IDs'
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(BotPrompt)
class BotPromptAdmin(admin.ModelAdmin):
    list_display = ('id', 'bot', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('bot__title', 'greeting', 'chat_prompt')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('bot',)
        }),
        ('Prompts', {
            'fields': ('greeting', 'chat_prompt', 'tracking_prompt', 'learning_goals')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(BotTheme)
class BotThemeAdmin(admin.ModelAdmin):
    list_display = ('id', 'bot', 'font_family', 'font_size', 'border_radius', 'created_at')
    list_filter = ('font_family', 'font_size', 'border_radius', 'message_spacing', 'created_at')
    search_fields = ('bot__title', 'bot__bot_group__title')
    readonly_fields = ('id', 'created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('bot',)
        }),
        ('Colors', {
            'fields': ('primary_color', 'accent_color', 'background_color', 'foreground_color'),
            'description': 'Theme colors in hex format (e.g., #8b5cf6)'
        }),
        ('Typography', {
            'fields': ('font_family', 'font_size')
        }),
        ('Layout', {
            'fields': ('border_radius', 'message_spacing')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
