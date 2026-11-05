from django.contrib import admin
from .models import SubscriptionCode, SubscriptionCodeAcceptance, BotGroupSchedule

@admin.register(SubscriptionCode)
class SubscriptionCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'get_access_type', 'get_target_name', 'limit', 'created_by', 'created_at')
    list_filter = ('created_at', 'created_by')
    search_fields = ('code', 'bot_group__title', 'bot__title')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('code', 'limit')
        }),
        ('Target', {
            'fields': ('bot_group', 'bot'),
            'description': 'Set either bot_group OR bot, not both.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        """Automatically set created_by to the current user if creating a new subscription code"""
        if not change:  # Only set created_by when creating new subscription codes
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        """Make created_by readonly when editing existing subscription codes"""
        readonly_fields = list(self.readonly_fields)
        if obj:  # If editing existing object
            readonly_fields.append('created_by')
        return readonly_fields

    def get_fieldsets(self, request, obj=None):
        """Add created_by field to fieldsets when editing existing subscription codes"""
        fieldsets = list(self.fieldsets)
        if obj:  # If editing existing object, show created_by as readonly
            fieldsets[0] = (None, {
                'fields': ('code', 'limit', 'created_by')
            })
        return fieldsets

    def get_access_type(self, obj):
        if obj.bot_group:
            return "Bot Group"
        elif obj.bot:
            return "Bot"
        return "Unknown"
    get_access_type.short_description = "Access Type"

    def get_target_name(self, obj):
        if obj.bot_group:
            return obj.bot_group.title
        elif obj.bot:
            return f"{obj.bot.bot_group.title} - {obj.bot.title}"
        return "Unknown"
    get_target_name.short_description = "Target"

@admin.register(SubscriptionCodeAcceptance)
class SubscriptionCodeAcceptanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'subscription_code', 'get_target_name', 'created_at')
    list_filter = ('created_at', 'subscription_code__bot_group', 'subscription_code__bot')
    search_fields = ('user__username', 'subscription_code__code')
    readonly_fields = ('created_at', 'updated_at')

    def get_target_name(self, obj):
        if obj.subscription_code.bot_group:
            return obj.subscription_code.bot_group.title
        elif obj.subscription_code.bot:
            return f"{obj.subscription_code.bot.bot_group.title} - {obj.subscription_code.bot.title}"
        return "Unknown"
    get_target_name.short_description = "Target"

@admin.register(BotGroupSchedule)
class BotGroupScheduleAdmin(admin.ModelAdmin):
    list_display = ('bot_group', 'bot', 'unlock_date', 'created_at')
    list_filter = ('bot_group', 'unlock_date', 'created_at')
    search_fields = ('bot_group__title', 'bot__title')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('bot_group', 'unlock_date')
