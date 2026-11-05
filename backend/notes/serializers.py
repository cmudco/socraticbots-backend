# notes/serializers.py
from rest_framework import serializers
from .models import Note
from django.utils import timezone

class NoteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source='public_id', read_only=True)
    user_id = serializers.UUIDField(source='user.public_id', read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)
    bot_id = serializers.UUIDField(source='bot.public_id', read_only=True)
    bot_title = serializers.CharField(source='bot.title', read_only=True)
    timestamp = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = ['id', 'title', 'content', 'timestamp',
                  'user_id', 'user_name', 'bot_id', 'bot_title', 
                  'created_at', 'updated_at']
        read_only_fields = ['id', 'user_id', 'user_name', 'bot_id', 'bot_title',
                           'timestamp', 'created_at', 'updated_at']

    def get_timestamp(self, obj):
        """Return a user-friendly timestamp"""
        now = timezone.now()
        diff = now - obj.created_at

        if diff.total_seconds() < 60:
            return "Just now"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif diff.total_seconds() < 86400:
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.days < 7:
            return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
        else:
            return obj.created_at.strftime("%b %d, %Y")