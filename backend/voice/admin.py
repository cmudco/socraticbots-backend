# voice/admin.py
from django.contrib import admin
from django.utils.html import format_html, format_html_join
from voice.constants import VoiceTeamRole
from voice.models import (
    VoiceTeam, VoiceTeamMembership, VoiceAgentMembership,
    VoiceAgent, VoiceAgentAccess, VoiceConversation, VoiceBrowserDiagnostic,
)


# ── Helpers ─────────────────────────────────────────────

# Choices for team role dropdown — hide "Admin" (reserved for future Co-Admin)
_ACTIVE_TEAM_ROLE_CHOICES = [
    (v, l) for v, l in VoiceTeamRole.choices if v != VoiceTeamRole.ADMIN
]


# ── Inlines ──────────────────────────────────────────────

class VoiceTeamMembershipInline(admin.TabularInline):
    model = VoiceTeamMembership
    extra = 1
    readonly_fields = ['created_at']
    autocomplete_fields = ['user', 'granted_by']

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'role':
            kwargs['choices'] = _ACTIVE_TEAM_ROLE_CHOICES
        return super().formfield_for_choice_field(db_field, request, **kwargs)


class VoiceAgentMembershipInline(admin.TabularInline):
    model = VoiceAgentMembership
    extra = 1
    readonly_fields = ['created_at']
    autocomplete_fields = ['user', 'granted_by']


class VoiceAgentAccessInline(admin.TabularInline):
    model = VoiceAgentAccess
    extra = 1
    readonly_fields = ['created_at']
    autocomplete_fields = ['user']

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        if obj is not None:
            formset.form.base_fields['max_attempts'].initial = obj.default_max_attempts
        return formset


# ── VoiceTeam ────────────────────────────────────────────

@admin.register(VoiceTeam)
class VoiceTeamAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_by', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'created_by__email']
    readonly_fields = ['created_at', 'updated_at']
    autocomplete_fields = ['created_by']
    ordering = ['-created_at']
    inlines = [VoiceTeamMembershipInline]


@admin.register(VoiceTeamMembership)
class VoiceTeamMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'team', 'role', 'granted_by', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['user__email', 'team__name']
    autocomplete_fields = ['user', 'team', 'granted_by']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'role':
            kwargs['choices'] = _ACTIVE_TEAM_ROLE_CHOICES
        return super().formfield_for_choice_field(db_field, request, **kwargs)


# ── VoiceAgent ───────────────────────────────────────────

@admin.register(VoiceAgent)
class VoiceAgentAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'user', 'team', 'voice_provider', 'status',
        'default_max_attempts', 'access_code', 'elevenlabs_agent_id', 'created_at',
    ]
    list_filter = ['status', 'voice_provider', 'team', 'created_at']
    search_fields = ['name', 'user__email', 'elevenlabs_agent_id', 'access_code']
    readonly_fields = ['elevenlabs_agent_id', 'created_at', 'updated_at']
    autocomplete_fields = ['user', 'team']
    ordering = ['-created_at']
    inlines = [VoiceAgentAccessInline, VoiceAgentMembershipInline]


@admin.register(VoiceAgentAccess)
class VoiceAgentAccessAdmin(admin.ModelAdmin):
    list_display = ['agent', 'user', 'max_attempts', 'created_at']
    list_filter = ['created_at']
    search_fields = ['agent__name', 'user__email']
    autocomplete_fields = ['agent', 'user']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(VoiceAgentMembership)
class VoiceAgentMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'agent', 'role', 'granted_by', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['user__email', 'agent__name']
    autocomplete_fields = ['user', 'agent', 'granted_by']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']


# ── VoiceConversation ────────────────────────────────────

def browser_evidence(events):
    if not events:
        return 'No browser evidence received. Absence does not establish a cause.'
    rows = format_html_join('', '<tr><td>{} ms</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>', (
        (event['elapsed_ms'], event['stage'], event['kind'],
         'online' if event['online'] else 'offline',
         event.get('error_name') or event.get('peer_state') or '—')
        for event in events
    ))
    return format_html(
        '<p>Browser-reported signals, relative to Start. Not a root-cause verdict.</p>'
        '<table><tr><th>Elapsed</th><th>Stage</th><th>Signal</th><th>Network hint</th><th>Detail</th></tr>{}</table>', rows,
    )


@admin.register(VoiceBrowserDiagnostic)
class VoiceBrowserDiagnosticAdmin(admin.ModelAdmin):
    list_display = ['attempt_id', 'agent', 'user', 'conversation', 'created_at', 'updated_at']
    list_filter = ['created_at', 'agent']
    search_fields = ['attempt_id', 'user__email', 'conversation__provider_conversation_id']
    readonly_fields = ['attempt_id', 'agent', 'user', 'conversation', 'evidence', 'created_at', 'updated_at']
    exclude = ['events']
    list_select_related = ['agent', 'user', 'conversation']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Browser evidence')
    def evidence(self, obj):
        return browser_evidence(obj.events)

@admin.register(VoiceConversation)
class VoiceConversationAdmin(admin.ModelAdmin):
    list_display = ['provider_conversation_id', 'elevenlabs_conversation_id', 'agent', 'user', 'status', 'started_at', 'duration_seconds']
    list_filter = ['status', 'agent__voice_provider', 'started_at']
    search_fields = ['provider_conversation_id', 'elevenlabs_conversation_id', 'user__email', 'agent__name']
    readonly_fields = [
        'elevenlabs_conversation_id', 'provider_conversation_id', 'started_at', 'ended_at',
        'duration_seconds', 'transcript', 'elevenlabs_deleted_at', 'compliance_receipt', 'browser_evidence',
    ]
    ordering = ['-started_at']

    @admin.display(description='Browser evidence')
    def browser_evidence(self, obj):
        diagnostic = getattr(obj, 'browser_diagnostic', None)
        return browser_evidence(diagnostic.events if diagnostic else [])
