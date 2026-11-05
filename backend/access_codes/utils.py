"""
Utility functions for access code-based permissions
"""
from django.db.models import Q

from bots.models import BotGroup, Bot
from .models import SubscriptionCodeAcceptance


def user_has_bot_group_access(user, bot_group):
    """
    Check if a user has access to a bot group via access codes.
    
    Args:
        user: User instance
        bot_group: BotGroup instance
        
    Returns:
        bool: True if user has access to the bot group
    """
    if user.is_creator:
        # Professors have access to bot groups they own/collaborate on
        # or that they have redeemed via access codes
        owns_or_collabs = bot_group.owner == user or bot_group.collaborators.filter(id=user.id).exists()
        if owns_or_collabs:
            return True
        return SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot_group=bot_group,
        ).exists() or SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot__bot_group=bot_group,
        ).exists()
    
    # Students have access via:
    # 1. Direct bot group-level access codes
    # 2. Any bot-level access codes within the bot group
    return SubscriptionCodeAcceptance.objects.filter(
        user=user
    ).filter(
        Q(subscription_code__bot_group=bot_group) | Q(subscription_code__bot__bot_group=bot_group)
    ).exists()


def user_has_bot_access(user, bot):
    """
    Check if a user has access to a bot via access codes.
    
    Args:
        user: User instance
        bot: Bot instance
        
    Returns:
        bool: True if user has access to the bot
    """
    if user.is_creator:
        # Professors have access to bots they created/collaborate on
        # or that they have redeemed via access codes
        has_role_access = (
            bot.user == user or
            bot.bot_group.owner == user or
            bot.bot_group.collaborators.filter(id=user.id).exists()
        )
        if has_role_access:
            return True
        return SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot=bot,
        ).exists() or SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot_group=bot.bot_group,
        ).exists()
    
    # Students have access via:
    # 1. Direct bot-level access codes
    # 2. Bot group-level access codes for the bot's group
    return SubscriptionCodeAcceptance.objects.filter(
        user=user
    ).filter(
        Q(subscription_code__bot=bot) | Q(subscription_code__bot_group=bot.bot_group)
    ).exists()


def get_user_accessible_bot_groups(user):
    """
    Get all bot groups that a user has access to.
    
    Args:
        user: User instance
        
    Returns:
        QuerySet: BotGroups the user can access
    """
    if user.is_creator:
        # Professors see groups they own/collaborate on or redeemed via access codes
        bot_group_level_access = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot_group__isnull=False
        ).values_list('subscription_code__bot_group', flat=True)

        bot_level_access = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot__isnull=False
        ).values_list('subscription_code__bot__bot_group', flat=True)

        return BotGroup.objects.filter(
            Q(owner=user) | Q(collaborators=user) | Q(id__in=list(bot_group_level_access) + list(bot_level_access))
        ).distinct()
    
    # Students see bot groups they have access to via:
    # 1. Bot group-level access codes
    # 2. Bot-level access codes (bot groups that contain bots they have access codes for)
    bot_group_level_access = SubscriptionCodeAcceptance.objects.filter(
        user=user,
        subscription_code__bot_group__isnull=False
    ).values_list('subscription_code__bot_group', flat=True)
    
    bot_level_access = SubscriptionCodeAcceptance.objects.filter(
        user=user,
        subscription_code__bot__isnull=False
    ).values_list('subscription_code__bot__bot_group', flat=True)
    
    accessible_bot_groups = list(bot_group_level_access) + list(bot_level_access)
    return BotGroup.objects.filter(id__in=accessible_bot_groups).distinct()


def get_user_accessible_bots(user, bot_group_id=None):
    """
    Get all bots that a user has access to.
    
    Args:
        user: User instance
        bot_group_id: Optional bot group ID to filter bots
        
    Returns:
        QuerySet: Bots the user can access
    """
    if user.is_creator:
        # Professors can access bots they created/collab on or redeemed via access codes
        # Direct bot access codes
        accessible_bots = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot__isnull=False
        ).values_list('subscription_code__bot', flat=True)

        # Bot group-level access codes - get all bots from groups user has access to
        accessible_bot_groups = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot_group__isnull=False
        ).values_list('subscription_code__bot_group', flat=True)

        base_query = Q(user=user) | Q(bot_group__owner=user) | Q(bot_group__collaborators=user) | Q(id__in=accessible_bots) | Q(bot_group__id__in=accessible_bot_groups)
    else:
        # Students can access bots via:
        # 1. Bots they created (for backward compatibility)
        # 2. Specific bot-level access codes
        # 3. Bot group-level access codes (all bots in groups they have access to)
        
        # Direct bot access codes
        accessible_bots = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot__isnull=False
        ).values_list('subscription_code__bot', flat=True)
        
        # Bot group-level access codes - get all bots from groups user has access to
        accessible_bot_groups = SubscriptionCodeAcceptance.objects.filter(
            user=user,
            subscription_code__bot_group__isnull=False
        ).values_list('subscription_code__bot_group', flat=True)
        
        base_query = Q(user=user) | Q(id__in=accessible_bots) | Q(bot_group__id__in=accessible_bot_groups)
    
    if bot_group_id:
        return Bot.objects.filter(base_query & Q(bot_group__id=bot_group_id)).distinct()
    return Bot.objects.filter(base_query).distinct()
