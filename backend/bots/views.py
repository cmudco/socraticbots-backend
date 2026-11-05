# bots/views.py
import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from access_codes.models import SubscriptionCode, SubscriptionCodeAcceptance
from utils.dare_api import models_client, files_client, auth_client
from utils.dare_api.base import DareApiError
from utils.internal_auth import require_internal_key

from .constants import MODEL_PREFERENCE_FIELDS
from .model_check_service import BotModelCheckService
from .model_dependency_service import BotModelDependencyService, ModelReference
from .models import BotGroup, Bot, BotModelPreference, BotPrompt, BotTheme, BotQuickPrompt
from .permissions import BotGroupPermission, BotPermission
from .serializers import (
    BotGroupSerializer, BotGroupDetailSerializer, BotSerializer, BotDetailSerializer,
    BotCreateSerializer
)

logger = logging.getLogger(__name__)

class BotGroupViewSet(viewsets.ModelViewSet):
    """
    ViewSet for BotGroup (formerly Book) operations
    Handles CRUD for bot groups with nested bot management
    """
    permission_classes = [permissions.IsAuthenticated, BotGroupPermission]
    
    def get_serializer_class(self):
        if self.action in ['retrieve', 'list']:
            return BotGroupDetailSerializer
        return BotGroupSerializer
    
    def get_queryset(self):
        user = self.request.user
        
        # Optional filter: only groups owned by the current user
        owned_only = self.request.query_params.get('owned_only')
        if owned_only in ('1', 'true', 'True'):
            return (
                BotGroup.objects
                .filter(owner=user)
                .distinct()
                .prefetch_related('bots', 'collaborators')
                .order_by('-created_at')
            )

        # Default: groups the user has access to
        # 1. Groups they own or collaborate on (professors)
        # 2. Groups they have access via bot group access codes
        # 3. Groups containing bots they have access to via individual bot access codes
        qs = (
            BotGroup.objects
            .filter(
                models.Q(owner=user) |
                models.Q(collaborators=user) |
                models.Q(subscription_codes__acceptances__user=user) | 
                models.Q(bots__subscription_codes__acceptances__user=user)
            )
            .distinct()
            .prefetch_related('bots', 'collaborators')
        )

        # Annotate for sorting: owners first, then redeemed (via access codes), then others
        redeemed_exists = SubscriptionCodeAcceptance.objects.filter(
            user=user
        ).filter(
            models.Q(subscription_code__bot_group=models.OuterRef('pk')) |
            models.Q(subscription_code__bot__bot_group=models.OuterRef('pk'))
        )

        qs = qs.annotate(
            is_owner=models.Case(
                models.When(owner=user, then=models.Value(1)),
                default=models.Value(0),
                output_field=models.IntegerField(),
            ),
            is_redeemed=models.Case(
                models.When(models.Exists(redeemed_exists), then=models.Value(1)),
                default=models.Value(0),
                output_field=models.IntegerField(),
            ),
        ).order_by('-is_owner', '-is_redeemed', '-created_at')

        return qs
    
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def update(self, request, *args, **kwargs):
        """Override update to handle access code"""
        instance = self.get_object()
        partial = kwargs.pop('partial', False)

        # Validate serializer
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        # Handle access code update if provided
        self._update_access_code_if_provided(instance, request.data)

        # Perform update and return refreshed data
        self.perform_update(serializer)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    def _get_user_token(self) -> str:
        """Extract the user's JWT token from the current request."""
        auth_header = self.request.META.get('HTTP_AUTHORIZATION', '')
        return auth_header.replace('Bearer ', '')

    def _update_access_code_if_provided(self, bot_group, data):
        """Update bot group access code if access_code or access_code_limit is in request."""
        if 'access_code' not in data and 'access_code_limit' not in data:
            return

        code = data.get('access_code')
        limit = self._normalize_limit(data.get('access_code_limit'))
        user_token = self._get_user_token()

        # Delete if code is empty or None
        if code == "" or code is None:
            # Deactivate in DARE if there was a previous code
            existing = SubscriptionCode.objects.filter(bot_group=bot_group).first()
            if existing:
                auth_client.sync_access_code_to_dare(
                    user_token=user_token,
                    access_code=existing.code, action="delete"
                )
            SubscriptionCode.objects.filter(bot_group=bot_group).delete()
            return

        # Create or update access code
        if code and code.strip():
            SubscriptionCode.objects.update_or_create(
                bot_group=bot_group,
                defaults={
                    'code': code.strip(),
                    'limit': limit if limit is not None else 0,
                    'created_by': self.request.user,
                }
            )
            # Sync to DARE
            auth_client.sync_access_code_to_dare(
                user_token=user_token,
                access_code=code.strip(),
                max_capacity=limit if limit is not None else 0,
            )
        # Update limit only if code not changing
        elif limit is not None:
            SubscriptionCode.objects.filter(bot_group=bot_group).update(limit=limit)
            # Also sync updated limit to DARE
            existing = SubscriptionCode.objects.filter(bot_group=bot_group).first()
            if existing:
                auth_client.sync_access_code_to_dare(
                    user_token=user_token,
                    access_code=existing.code,
                    max_capacity=limit,
                )

    def _normalize_limit(self, limit_value):
        """Convert limit to int, handling empty string and invalid values"""
        if limit_value is None:
            return None
        if limit_value == "":
            return 0
        try:
            return int(limit_value)
        except (TypeError, ValueError):
            return None

    @action(detail=True, methods=['post'])
    def add_collaborator(self, request, pk=None):
        """Add a collaborator to the bot group"""
        bot_group = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = get_user_model().objects.get(id=user_id)
            bot_group.collaborators.add(user)
            return Response({'message': 'Collaborator added successfully'})
        except get_user_model().DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['delete'])
    def remove_collaborator(self, request, pk=None):
        """Remove a collaborator from the bot group"""
        bot_group = self.get_object()
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = get_user_model().objects.get(id=user_id)
            bot_group.collaborators.remove(user)
            return Response({'message': 'Collaborator removed successfully'})
        except get_user_model().DoesNotExist:
            return Response(
                {'error': 'User not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class BotViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Bot (formerly Chapter) operations
    Handles CRUD for individual bots within bot groups
    """
    permission_classes = [permissions.IsAuthenticated, BotPermission]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return BotCreateSerializer
        elif self.action == 'retrieve':
            return BotDetailSerializer
        return BotSerializer
    
    def get_queryset(self):
        user = self.request.user
        
        bot_group_id = self.kwargs.get('bot_group_pk')
        if bot_group_id:
            # Ensure user has access to the bot group
            bot_group_queryset = BotGroup.objects.filter(
                models.Q(owner=user) | 
                models.Q(collaborators=user) |
                models.Q(subscription_codes__acceptances__user=user) |  # Bot group access
                models.Q(bots__subscription_codes__acceptances__user=user)  # Individual bot access
            ).distinct()
            
            bot_group = get_object_or_404(bot_group_queryset, pk=bot_group_id)
            
            # For students, filter bots to only those they have specific access to
            if user.is_student:
                # Students see only bots they have access to via:
                # 1. Bot group access codes (all bots in the group)
                # 2. Individual bot access codes
                return Bot.objects.filter(
                    bot_group=bot_group
                ).filter(
                    models.Q(bot_group__subscription_codes__acceptances__user=user) |  # Group access
                    models.Q(subscription_codes__acceptances__user=user)  # Individual access
                ).distinct().select_related('bot_group', 'user', 'model_preference', 'prompts', 'theme')
            else:
                # Professors see all bots in groups they own/collaborate on
                return Bot.objects.filter(bot_group=bot_group).select_related(
                    'bot_group', 'user', 'model_preference', 'prompts', 'theme'
                )
        
        # If no bot_group_pk, return all bots user has access to
        if user.is_student:
            # Students see only bots they have specific access to
            return Bot.objects.filter(
                models.Q(bot_group__subscription_codes__acceptances__user=user) |
                models.Q(subscription_codes__acceptances__user=user)
            ).distinct().select_related('bot_group', 'user', 'model_preference', 'prompts', 'theme')
        else:
            # Professors see bots they created
            return Bot.objects.filter(user=user).select_related(
                'bot_group', 'user', 'model_preference', 'prompts', 'theme'
            )
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['bot_group_id'] = self.kwargs.get('bot_group_pk')
        return context
    
    def create(self, request, *args, **kwargs):
        """Override create to handle inline fields"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get bot group
        bot_group_id = self.kwargs.get('bot_group_pk')
        if bot_group_id:
            # Only owners can create bots (not collaborators or students)
            bot_group_queryset = BotGroup.objects.filter(owner=request.user).distinct()
            bot_group = get_object_or_404(bot_group_queryset, pk=bot_group_id)
        else:
            bot_group = None
        
        title = serializer.validated_data.get('title')
        if bot_group and title:
            existing_bot = Bot.objects.filter(
                bot_group=bot_group,
                title=title,
                user=request.user
            ).first()
            
            if existing_bot:
                serializer = self.get_serializer(existing_bot)
                headers = self.get_success_headers(serializer.data)
                return Response(serializer.data, status=status.HTTP_200_OK, headers=headers)
        
        BotModelCheckService.check(request.user.external_user_id, request.data)

        # Create the bot first
        bot = serializer.save(user=request.user, bot_group=bot_group)
        
        # Handle inline fields using existing helper methods
        # Access code handling
        if 'access_code' in request.data or 'access_code_limit' in request.data:
            self._update_access_code_if_provided(bot, request.data)
        
        # Model preferences
        self._update_model_preferences_if_provided(bot, request.data)
        
        # Prompts
        self._update_prompts_if_provided(bot, request.data)

        # Theme
        self._update_theme_if_provided(bot, request.data)

        # Quick prompts
        self._update_quick_prompts_if_provided(bot, request.data)

        # Refresh and return updated data
        bot.refresh_from_db()
        serializer = self.get_serializer(bot)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
    
    def perform_create(self, serializer):
        # This method is now handled by the create override above
        pass
    
    def update(self, request, *args, **kwargs):
        """Override update to handle access code, model preferences, and prompts"""
        instance = self.get_object()
        partial = kwargs.pop('partial', False)

        # Validate serializer
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        BotModelCheckService.check(
            instance.user.external_user_id, request.data, bot=instance
        )

        # Update nested resources if provided
        self._update_access_code_if_provided(instance, request.data)
        self._update_model_preferences_if_provided(instance, request.data)
        self._update_prompts_if_provided(instance, request.data)
        self._update_theme_if_provided(instance, request.data)
        self._update_quick_prompts_if_provided(instance, request.data)

        # Perform update and return refreshed data
        self.perform_update(serializer)
        self._clear_prefetch_cache(instance)
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    def _extract_fields_from_request(self, data, field_names):
        """Extract only fields that are present in request data"""
        return {field: data[field] for field in field_names if field in data}

    def _update_model_preferences_if_provided(self, bot, data):
        """Update model preferences if chat_model_dare_id or tracking_model_dare_id is in request"""
        fields = self._extract_fields_from_request(data, MODEL_PREFERENCE_FIELDS)
        if not fields:
            return

        BotModelPreference.objects.update_or_create(bot=bot, defaults=fields)

    def _update_prompts_if_provided(self, bot, data):
        """Update prompts if any prompt field is in request"""
        fields = self._extract_fields_from_request(
            data, ['greeting', 'chat_prompt', 'tracking_prompt', 'learning_goals']
        )
        if not fields:
            return

        BotPrompt.objects.update_or_create(bot=bot, defaults=fields)

    def _update_theme_if_provided(self, bot, data):
        """Update theme if provided in request. DRF CamelCase handles field conversion."""
        theme_data = data.get('theme')
        if theme_data and isinstance(theme_data, dict):
            BotTheme.objects.update_or_create(bot=bot, defaults=theme_data)

    def _update_quick_prompts_if_provided(self, bot, data):
        """Update quick prompts if quick_prompts_data is in request.
        Replaces all existing quick prompts with the new list.
        """
        quick_prompts_data = data.get('quick_prompts_data')
        if quick_prompts_data is None:
            return
        
        if not isinstance(quick_prompts_data, list):
            return
        
        # Delete existing quick prompts for this bot
        BotQuickPrompt.objects.filter(bot=bot).delete()
        
        # Create new quick prompts
        for i, prompt_data in enumerate(quick_prompts_data):
            if isinstance(prompt_data, dict) and prompt_data.get('title') and prompt_data.get('prompt'):
                BotQuickPrompt.objects.create(
                    bot=bot,
                    title=prompt_data['title'][:100],  # Enforce max length
                    prompt=prompt_data['prompt'],
                    order=prompt_data.get('order', i)
                )

    def _clear_prefetch_cache(self, instance):
        """Clear Django's prefetch cache if it exists"""
        if hasattr(instance, '_prefetched_objects_cache'):
            instance._prefetched_objects_cache = {}
    
    def _get_user_token(self) -> str:
        """Extract the user's JWT token from the current request."""
        auth_header = self.request.META.get('HTTP_AUTHORIZATION', '')
        return auth_header.replace('Bearer ', '')

    def _update_access_code_if_provided(self, bot, data):
        """Update bot access code if access_code or access_code_limit is in request."""
        if 'access_code' not in data and 'access_code_limit' not in data:
            return

        code = data.get('access_code')
        limit = self._normalize_limit(data.get('access_code_limit'))
        user_token = self._get_user_token()

        # Delete if code is empty or None
        if code == "" or code is None:
            # Deactivate in DARE if there was a previous code
            existing = SubscriptionCode.objects.filter(bot=bot).first()
            if existing:
                auth_client.sync_access_code_to_dare(
                    user_token=user_token,
                    access_code=existing.code, action="delete"
                )
            SubscriptionCode.objects.filter(bot=bot).delete()
            return

        # Create or update access code
        if code and code.strip():
            SubscriptionCode.objects.update_or_create(
                bot=bot,
                defaults={
                    'code': code.strip(),
                    'limit': limit if limit is not None else 0,
                    'created_by': self.request.user,
                }
            )
            # Sync to DARE
            auth_client.sync_access_code_to_dare(
                user_token=user_token,
                access_code=code.strip(),
                max_capacity=limit if limit is not None else 0,
            )
        # Update limit only if code not changing
        elif limit is not None:
            SubscriptionCode.objects.filter(bot=bot).update(limit=limit)
            # Also sync updated limit to DARE
            existing = SubscriptionCode.objects.filter(bot=bot).first()
            if existing:
                auth_client.sync_access_code_to_dare(
                    user_token=user_token,
                    access_code=existing.code,
                    max_capacity=limit,
                )

    def _normalize_limit(self, limit_value):
        """Convert limit to int, handling empty string and invalid values"""
        if limit_value is None:
            return None
        if limit_value == "":
            return 0
        try:
            return int(limit_value)
        except (TypeError, ValueError):
            return None
    
    @action(detail=True, methods=['post'])
    def attach_files(self, request, pk=None, bot_group_pk=None):
        """Attach DARE files to a bot"""
        bot = self.get_object()
        file_ids = request.data.get('file_ids', [])
        
        if not isinstance(file_ids, list):
            return Response(
                {'error': 'file_ids must be a list'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file IDs with DARE backend
        try:
            # Verify files exist in DARE
            for file_id in file_ids:
                files_client.get_file_content(file_id)
            
            # Update bot's file IDs
            current_file_ids = bot.dare_file_ids or []
            new_file_ids = list(set(current_file_ids + file_ids))
            bot.dare_file_ids = new_file_ids
            bot.save()
            
            return Response({
                'message': 'Files attached successfully',
                'file_ids': new_file_ids
            })
        except DareApiError as e:
            return Response(
                {'error': f'Error validating files: {str(e)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def detach_files(self, request, pk=None, bot_group_pk=None):
        """Detach DARE files from a bot"""
        bot = self.get_object()
        file_ids = request.data.get('file_ids', [])
        
        if not isinstance(file_ids, list):
            return Response(
                {'error': 'file_ids must be a list'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        current_file_ids = bot.dare_file_ids or []
        new_file_ids = [fid for fid in current_file_ids if fid not in file_ids]
        bot.dare_file_ids = new_file_ids
        bot.save()
        
        return Response({
            'message': 'Files detached successfully',
            'file_ids': new_file_ids
        })

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None, bot_group_pk=None):
        """Clone a bot in the same group with title prefixed by 'Copy - '."""
        bot = self.get_object()

        # Only group owner can clone
        if bot.bot_group.owner != request.user:
            return Response({'error': 'Only the group owner can clone bots.'}, status=status.HTTP_403_FORBIDDEN)

        # Create the cloned bot
        cloned_bot = Bot.objects.create(
            bot_group=bot.bot_group,
            user=request.user,
            title=f"Copy - {bot.title}",
            subject=bot.subject,
            topic=bot.topic,
            dare_file_ids=list(bot.dare_file_ids or []),
            chat_history_limit=bot.chat_history_limit,
            tracking_history_limit=bot.tracking_history_limit,
        )
        # Copy advanced flag
        cloned_bot.is_advanced = getattr(bot, 'is_advanced', False)
        cloned_bot.save(update_fields=['is_advanced'])

        # Clone model preferences if exist
        try:
            pref = bot.model_preference
            BotModelPreference.objects.create(
                bot=cloned_bot,
                chat_model_dare_id=pref.chat_model_dare_id,
                tracking_model_dare_id=pref.tracking_model_dare_id,
            )
        except BotModelPreference.DoesNotExist:
            logger.info(
                "No model preferences to clone for bot %s",
                getattr(bot, 'id', bot)
            )

        # Clone prompts if exist
        try:
            prompts = bot.prompts
            BotPrompt.objects.create(
                bot=cloned_bot,
                greeting=prompts.greeting,
                chat_prompt=prompts.chat_prompt,
                tracking_prompt=prompts.tracking_prompt,
                learning_goals=prompts.learning_goals,
            )
        except BotPrompt.DoesNotExist:
            logger.info(
                "No prompts to clone for bot %s",
                getattr(bot, 'id', bot)
            )

        serializer = self.get_serializer(cloned_bot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_dare_llms(request, model_id=None):
    """
    Proxy endpoint to fetch LLM models from DARE backend
    Supports both list all models and individual model fetch
    """
    try:
        # Get user token from request
        user_token = None
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            user_token = auth_header.split(' ')[1]
        
        if model_id:
            # Fetch individual model
            model_data = models_client.get_llm_model(int(model_id), user_token)
            return Response(model_data, status=status.HTTP_200_OK)

        wallet_scope = request.query_params.get('wallet_scope')
        if wallet_scope:
            envelope = models_client.get_wallet_scoped_models(
                wallet_scope, user_token
            )
            return Response(envelope, status=status.HTTP_200_OK)

        # Legacy: full catalog
        models_data = models_client.get_llm_models(user_token)
        return Response(models_data, status=status.HTTP_200_OK)
        
    except DareApiError as e:
        logger.error(f"Error fetching DARE LLM models: {str(e)}")
        return Response(
            {'error': e.message or 'Failed to fetch LLM models from DARE backend'},
            status=e.status_code if e.status_code and e.status_code < 500
            else status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching DARE LLM models: {str(e)}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def get_bots_using_model(request, model_id):
    """Return every Socratic bot that stores the given DARE model ID."""
    return Response(BotModelDependencyService.preview(model_id).to_dict())


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def nullify_model_references(request, model_id):
    """Clear the model from affected bots and deactivate them atomically."""
    result = BotModelDependencyService.nullify(model_id)
    logger.info(
        "Nullified model %s references for %s Socratic bots",
        model_id,
        result.affected_bots_count,
    )
    return Response(result.to_dict())


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def get_bots_using_litellm_key(request, key_id):
    """Return every Socratic bot whose model routes through the LiteLLM key."""
    bots = BotModelDependencyService.dependencies(ModelReference.litellm_key(key_id))
    return Response(
        {
            'litellm_key_id': str(key_id),
            'dependent_bots_count': len(bots),
            'dependent_bots': [bot.to_dict() for bot in bots],
        }
    )


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def nullify_litellm_key_references(request, key_id):
    """Clear a deleted LiteLLM key's models from bots and deactivate them."""
    result = BotModelDependencyService.clear(ModelReference.litellm_key(key_id))
    logger.info(
        "Cleared LiteLLM key %s from %s Socratic bots",
        key_id,
        result.affected_bots_count,
    )
    return Response(result.to_dict())


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def update_bot_cap(request, bot_id):
    raw = request.data.get('budget')
    if raw is None:
        return Response({'error': 'budget is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        new_cap = Decimal(str(raw))
    except (ArithmeticError, ValueError, TypeError):
        return Response({'error': 'budget must be a number'}, status=status.HTTP_400_BAD_REQUEST)

    if new_cap <= 0:
        return Response({'error': 'budget must be positive'}, status=status.HTTP_400_BAD_REQUEST)

    bot = Bot.objects.only('id', 'budget', 'budget_used').filter(pk=bot_id).first()
    if bot is None:
        return Response({'error': 'Bot not found'}, status=status.HTTP_404_NOT_FOUND)

    used = bot.budget_used or Decimal('0')
    if new_cap < used:
        return Response(
            {
                'error': 'cap_below_used',
                'message': f'Cannot lower cap below current usage (${used} spent).',
                'budget_used': float(used),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    Bot.objects.filter(pk=bot_id).update(budget=new_cap)
    logger.info("update_bot_cap: bot %s cap %s -> %s", bot_id, bot.budget, new_cap)

    return Response({
        'success': True,
        'budget': float(new_cap),
        'budget_used': float(used),
    })


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def get_bot_billing_config(request, bot_id):
    """
    Internal endpoint: return the slice DARE needs to decide whose wallet pays.

    Per-bot ``billing_source`` was removed — billing now follows a simple rule
    DARE applies on its side: charge the requester if authenticated; otherwise
    (anonymous public-bot traffic) charge the bot owner.
    """
    bot = (
        Bot.objects
        .select_related('user')
        .filter(pk=bot_id)
        .only(
            'id', 'budget', 'budget_used', 'is_publicly_deployed', 'is_active',
            'user__external_user_id',
        )
        .first()
    )
    if bot is None:
        return Response({'error': 'Bot not found'}, status=status.HTTP_404_NOT_FOUND)

    preference = BotModelPreference.objects.filter(bot=bot).first()
    return Response({
        'botId': bot.id,
        'ownerDareUserId': getattr(bot.user, 'external_user_id', None),
        'chatModelDareId': preference.chat_model_dare_id if preference else None,
        'trackingModelDareId': preference.tracking_model_dare_id if preference else None,
        'budget': str(bot.budget) if bot.budget is not None else None,
        'budgetUsed': str(bot.budget_used or 0),
        'isPubliclyDeployed': bot.is_publicly_deployed,
        'isActive': bot.is_active,
        'billingRule': 'AUTO_REQUESTER_OR_OWNER',
    })


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([])
@require_internal_key
def update_bot_budget(request):
    bot_id = request.data.get('bot_id')
    cost = request.data.get('cost')

    if bot_id is None or cost is None:
        return Response(
            {'error': 'bot_id and cost are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        cost_decimal = Decimal(str(cost))
    except (ArithmeticError, ValueError, TypeError):
        return Response({'error': 'cost must be a number'}, status=status.HTTP_400_BAD_REQUEST)

    if cost_decimal <= 0:
        return Response({'success': True, 'ignored': True})

    bot_pre = Bot.objects.only('id', 'budget', 'budget_used').filter(pk=bot_id).first()
    if bot_pre is None:
        return Response({'error': 'Bot not found'}, status=status.HTTP_404_NOT_FOUND)

    pre_used = bot_pre.budget_used or Decimal('0')
    cap = bot_pre.budget

    Bot.objects.filter(pk=bot_id).update(
        budget_used=models.F('budget_used') + cost_decimal
    )
    bot = Bot.objects.only('id', 'budget', 'budget_used').get(pk=bot_id)
    post_used = bot.budget_used

    cap_status = 'OK'
    if cap is not None and cap > 0:
        threshold_80 = cap * Decimal('0.80')
        crossed_80 = pre_used < threshold_80 <= post_used
        crossed_100 = pre_used < cap <= post_used
        if crossed_100:
            cap_status = 'CAP_REACHED'
            logger.error("bot %s reached cap: $%s used of $%s", bot_id, post_used, cap)
        elif crossed_80:
            cap_status = 'APPROACHING_CAP'
            logger.warning("bot %s approaching cap: $%s used of $%s", bot_id, post_used, cap)

    logger.info("Updated public deployment budget for bot %s: +$%s, total: $%s", bot_id, cost_decimal, post_used)

    return Response({
        'success': True,
        'budget_used': float(post_used),
        'budget': float(cap) if cap is not None else None,
        'cap_status': cap_status,
    })
