# notes/admin.py
from django.contrib import admin
from .models import Note

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('title', 'bot', 'user', 'created_at', 'updated_at')
    list_filter = ('bot', 'created_at', 'user')
    search_fields = ('title', 'content', 'user__username', 'bot__title')
    readonly_fields = ('public_id', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {
            'fields': ('public_id', 'title', 'content', 'bot', 'user')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
