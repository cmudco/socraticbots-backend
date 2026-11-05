"""
Role-based permission classes for Socratic Bots.

Roles are sourced from DARE JWT tokens and cached on the user object
by JWTAuthentication during request authentication.
"""
from rest_framework.permissions import BasePermission


class IsCreator(BasePermission):
    """
    Permission class that allows only Creator-role users (professors) and above.
    Creators can create and manage bots/bot groups.
    """
    message = "Only creators can perform this action."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.is_creator


class IsStudent(BasePermission):
    """
    Permission class that verifies user is a student (basic User role).
    Students can only subscribe to and interact with bots.
    """
    message = "Only students can perform this action."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.is_student


class CanManageBot(BasePermission):
    """
    Object-level permission that checks if the user can manage a specific bot
    or bot group (must be owner or collaborator).
    """
    message = "You do not have permission to manage this resource."

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Check ownership
        if hasattr(obj, 'created_by') and obj.created_by == request.user:
            return True
        if hasattr(obj, 'user') and obj.user == request.user:
            return True
        if hasattr(obj, 'owner') and obj.owner == request.user:
            return True

        # Check collaboration
        if hasattr(obj, 'collaborators'):
            return obj.collaborators.filter(id=request.user.id).exists()

        # For bots, check bot_group ownership/collaboration
        if hasattr(obj, 'bot_group'):
            bot_group = obj.bot_group
            if bot_group.owner == request.user:
                return True
            if bot_group.collaborators.filter(id=request.user.id).exists():
                return True

        return False
