from rest_framework import permissions

from .models import BotGroup


class BotGroupPermission(permissions.BasePermission):
    """Allow authenticated access generally, but restrict modifications to the owner."""

    def has_permission(self, request, view):
        # Allow all authenticated users to list/retrieve/create
        if not request.user or not request.user.is_authenticated:
            return False
        return True

    def has_object_permission(self, request, view, obj):
        # Safe methods always allowed
        if request.method in permissions.SAFE_METHODS:
            return True

        # Only the owner can modify or perform custom actions
        owner_required_actions = {
            'update', 'partial_update', 'destroy', 'add_collaborator', 'remove_collaborator'
        }
        if getattr(view, 'action', None) in owner_required_actions:
            return getattr(obj, 'owner_id', None) == getattr(request.user, 'id', None)

        # Default to owner-only for non-safe methods
        return getattr(obj, 'owner_id', None) == getattr(request.user, 'id', None)


class BotPermission(permissions.BasePermission):
    """Restrict bot modifications to the bot creator; viewing accessible via queryset rules."""

    def has_permission(self, request, view):
        # Auth required
        if not request.user or not request.user.is_authenticated:
            return False

        # For creation, ensure the user owns the parent bot group
        if getattr(view, 'action', None) == 'create':
            bot_group_pk = view.kwargs.get('bot_group_pk')
            if not bot_group_pk:
                return False
            try:
                return BotGroup.objects.filter(id=bot_group_pk, owner=request.user).exists()
            except Exception:
                return False

        return True

    def has_object_permission(self, request, view, obj):
        # Safe methods allowed
        if request.method in permissions.SAFE_METHODS:
            return True

        # Only the bot creator can update/delete
        if getattr(view, 'action', None) in {'update', 'partial_update', 'destroy'}:
            return getattr(obj, 'user_id', None) == getattr(request.user, 'id', None)

        return True

