# bots/serializers.py
from rest_framework import serializers
from django.db import models
from .models import BotGroup, Bot, BotModelPreference, BotPrompt, BotTheme, BotQuickPrompt
from access_codes.models import SubscriptionCodeAcceptance


class BotGroupSerializer(serializers.ModelSerializer):
    """
    Serializer for BotGroup (formerly Book)
    """
    bots_count = serializers.SerializerMethodField()
    # Expose owner id to allow frontend to determine ownership
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    # Expose owner's DARE user ID for file_owner_id in chat requests
    owner_dare_id = serializers.IntegerField(source='owner.external_user_id', read_only=True)
    # Whether current user has redeemed access (group or any bot in group)
    redeemed = serializers.SerializerMethodField()
    # Access code for the bot group
    access_code = serializers.SerializerMethodField()

    class Meta:
        model = BotGroup
        fields = ['id', 'title', 'description', 'bots_count', 'owner_id', 'owner_dare_id', 'redeemed', 'access_code', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_bots_count(self, obj):
        return obj.bots.count()

    def create(self, validated_data):
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)

    def get_access_code(self, obj):
        """Get the access code for this bot group, if any"""
        try:
            access_code_obj = obj.subscription_codes.first()
            if access_code_obj:
                used_count = SubscriptionCodeAcceptance.objects.filter(subscription_code=access_code_obj).count()
                return {
                    'code': access_code_obj.code,
                    'limit': access_code_obj.limit,
                    'used': used_count,
                    'created_at': access_code_obj.created_at,
                    'created_by': access_code_obj.created_by.email if access_code_obj.created_by else None
                }
            return None
        except AttributeError:
            return None

    def get_redeemed(self, obj):
        try:
            user = self.context['request'].user
        except Exception:
            return False
        try:
            return SubscriptionCodeAcceptance.objects.filter(
                subscription_code__bot_group=obj,
                user=user
            ).exists() or SubscriptionCodeAcceptance.objects.filter(
                subscription_code__bot__bot_group=obj,
                user=user
            ).exists()
        except Exception:
            return False


class BotModelPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for BotModelPreference using DARE LLM IDs
    """
    class Meta:
        model = BotModelPreference
        fields = ['id', 'chat_model_dare_id', 'tracking_model_dare_id', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BotPromptSerializer(serializers.ModelSerializer):
    """
    Serializer for BotPrompt
    """
    class Meta:
        model = BotPrompt
        fields = ['id', 'greeting', 'chat_prompt', 'tracking_prompt', 'learning_goals', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BotThemeSerializer(serializers.ModelSerializer):
    """
    Serializer for BotTheme with camelCase field names for frontend
    """
    primaryColor = serializers.CharField(source='primary_color')
    accentColor = serializers.CharField(source='accent_color')
    backgroundColor = serializers.CharField(source='background_color')
    foregroundColor = serializers.CharField(source='foreground_color')
    fontFamily = serializers.CharField(source='font_family')
    fontSize = serializers.CharField(source='font_size')
    borderRadius = serializers.CharField(source='border_radius')
    messageSpacing = serializers.CharField(source='message_spacing')
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    updatedAt = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = BotTheme
        fields = [
            'id', 'primaryColor', 'accentColor', 'backgroundColor', 'foregroundColor',
            'fontFamily', 'fontSize', 'borderRadius', 'messageSpacing',
            'createdAt', 'updatedAt'
        ]
        read_only_fields = ['id', 'createdAt', 'updatedAt']


class BotQuickPromptSerializer(serializers.ModelSerializer):
    """
    Serializer for BotQuickPrompt - quick template prompts displayed as pills
    """
    class Meta:
        model = BotQuickPrompt
        fields = ['id', 'title', 'prompt', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class BotSerializer(serializers.ModelSerializer):
    """
    Serializer for Bot (formerly Chapter)
    """
    model_preference = BotModelPreferenceSerializer(read_only=True)
    prompts = BotPromptSerializer(read_only=True)
    theme = BotThemeSerializer(read_only=True)
    quick_prompts = BotQuickPromptSerializer(many=True, read_only=True)
    files_count = serializers.SerializerMethodField()
    access_code = serializers.SerializerMethodField()
    # Expose creator id (user id) so frontend can restrict actions
    created_by_id = serializers.IntegerField(source='user.id', read_only=True)
    # Expose creator's DARE user ID for file_owner_id in chat requests
    created_by_dare_id = serializers.IntegerField(source='user.external_user_id', read_only=True)
    # Whether current user accessed this bot via a redeemed access code (bot or group)
    redeemed = serializers.SerializerMethodField()

    # Model preference fields that can be updated inline. Stored as the
    # opaque picker id from DARE (stringified PK or "litellm:<key>:<name>"),
    # so accept any non-empty string and pass it through verbatim.
    chat_model_dare_id = serializers.CharField(required=False, write_only=True, allow_null=True)
    tracking_model_dare_id = serializers.CharField(required=False, write_only=True, allow_null=True)

    # Prompt fields that can be updated inline
    greeting = serializers.CharField(required=False, write_only=True, allow_blank=True)
    chat_prompt = serializers.CharField(required=False, write_only=True, allow_blank=True)
    tracking_prompt = serializers.CharField(required=False, write_only=True, allow_blank=True)
    learning_goals = serializers.CharField(required=False, write_only=True, allow_blank=True)

    # Theme fields that can be updated inline (using Dict to accept full theme object)
    theme_data = serializers.DictField(required=False, write_only=True, child=serializers.CharField())
    
    # Quick prompts field for inline updates (accepts list of {title, prompt, order})
    quick_prompts_data = serializers.ListField(
        required=False, 
        write_only=True,
        child=serializers.DictField()
    )
    
    class Meta:
        model = Bot
        fields = [
            'id', 'title', 'subject', 'topic', 'dare_file_ids', 'files_count', 'is_advanced', 'quick_prompts',
            'is_active', 'web_search_enabled', 'rag_mode', 'max_context_snippets', 'document_similarity_threshold',
            'chat_history_limit', 'tracking_history_limit',
            'is_publicly_deployed', 'budget', 'budget_used',
            'model_preference', 'prompts', 'theme', 'access_code',
            'chat_model_dare_id', 'tracking_model_dare_id',
            'greeting', 'chat_prompt', 'tracking_prompt', 'learning_goals',
            'theme_data', 'quick_prompts_data',
            'created_at', 'updated_at', 'created_by_id', 'created_by_dare_id', 'redeemed'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'budget_used']

    def validate(self, attrs):
        attrs = super().validate(attrs)

        instance = getattr(self, 'instance', None)
        is_publicly_deployed = attrs.get(
            'is_publicly_deployed',
            getattr(instance, 'is_publicly_deployed', False) if instance else False,
        )
        budget = attrs.get('budget', getattr(instance, 'budget', None) if instance else None)
        budget_used = getattr(instance, 'budget_used', 0) if instance else 0

        if is_publicly_deployed and (budget is None or budget <= 0):
            raise serializers.ValidationError({
                'budget': (
                    'Public deployment requires a positive budget cap. '
                    'Set a non-zero amount before enabling.'
                )
            })

        if 'budget' in attrs and attrs['budget'] is not None and attrs['budget'] < budget_used:
            raise serializers.ValidationError({
                'budget': f'Cannot lower budget below current usage (${budget_used} already spent).'
            })

        return attrs

    def get_files_count(self, obj):
        return len(obj.dare_file_ids) if obj.dare_file_ids else 0
    
    def get_access_code(self, obj):
        """Get the access code for this bot, if any"""
        try:
            access_code_obj = obj.subscription_codes.first()
            if access_code_obj:
                used_count = SubscriptionCodeAcceptance.objects.filter(subscription_code=access_code_obj).count()
                return {
                    'code': access_code_obj.code,
                    'limit': access_code_obj.limit,
                    'used': used_count,
                    'created_at': access_code_obj.created_at,
                    'created_by': access_code_obj.created_by.email if access_code_obj.created_by else None
                }
            return None
        except AttributeError:
            return None

    def get_redeemed(self, obj):
        """Return True if the current user has redeemed an access code that grants access to this bot."""
        try:
            user = self.context['request'].user
        except Exception:
            return False
        try:
            return SubscriptionCodeAcceptance.objects.filter(
                subscription_code__bot=obj,
                user=user
            ).exists() or SubscriptionCodeAcceptance.objects.filter(
                subscription_code__bot_group=obj.bot_group,
                user=user
            ).exists()
        except Exception:
            return False
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        # bot_group should be passed from the view context
        bot_group_id = self.context.get('bot_group_id')
        if bot_group_id:
            validated_data['bot_group_id'] = bot_group_id
        return super().create(validated_data)


class BotDetailSerializer(BotSerializer):
    """
    Detailed serializer for Bot with full nested data
    """
    bot_group = BotGroupSerializer(read_only=True)
    
    class Meta(BotSerializer.Meta):
        fields = BotSerializer.Meta.fields + ['bot_group']


class BotGroupDetailSerializer(BotGroupSerializer):
    """
    Detailed serializer for BotGroup with bots
    """
    bots = serializers.SerializerMethodField()
    collaborators = serializers.StringRelatedField(many=True, read_only=True)
    
    class Meta(BotGroupSerializer.Meta):
        fields = BotGroupSerializer.Meta.fields + ['bots', 'collaborators']
    
    def get_bots(self, obj):
        """Get only bots the user has access to"""
        user = self.context['request'].user
        
        # Filter bots based on user access
        accessible_bots = obj.bots.filter(
            models.Q(bot_group__subscription_codes__acceptances__user=user) |  # Group access
            models.Q(subscription_codes__acceptances__user=user) |  # Individual bot access
            models.Q(user=user) |  # Bot creator
            models.Q(bot_group__owner=user) |  # Bot group owner
            models.Q(bot_group__collaborators=user)  # Bot group collaborator
        ).distinct()
        
        return BotSerializer(accessible_bots, many=True, context=self.context).data


# Simplified serializers for quick operations
class BotCreateSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for bot creation
    """
    class Meta:
        model = Bot
        fields = [
            'id', 'title', 'subject', 'topic', 'is_advanced', 'is_active', 'web_search_enabled',
            'rag_mode', 'max_context_snippets', 'document_similarity_threshold',
            'chat_history_limit', 'tracking_history_limit',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        bot_group_id = self.context.get('bot_group_id')
        if bot_group_id:
            validated_data['bot_group_id'] = bot_group_id
        return super().create(validated_data)
