import logging

from django.db import transaction
from rest_framework import serializers

from users.models import CustomUser
from utils.dare_api import auth_client, DareApiError
from voice.access_codes import (
    VOICE_PROVISIONER,
    VoiceAccessCodeError,
    ensure_signup_code_in_dare,
    grant_voice_access,
    resolve_voice_signup_code,
)
from .models import SubscriptionCode, SubscriptionCodeAcceptance

logger = logging.getLogger(__name__)

class SubscriptionCodeSerializer(serializers.ModelSerializer):
    target_name = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()
    access_type = serializers.SerializerMethodField()
    used = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionCode
        fields = ['code', 'target_name', 'target_type', 'access_type', 'created_at', 'limit', 'used']
        read_only_fields = ['created_at']

    def get_target_name(self, obj):
        if obj.bot_group:
            bot_count = obj.bot_group.bots.count()
            if bot_count > 0:
                return f"{obj.bot_group.title} (Bot Group - {bot_count} bots)"
            else:
                return f"{obj.bot_group.title} (Bot Group)"
        elif obj.bot:
            return f"{obj.bot.bot_group.title} - {obj.bot.title}"
        return "Unknown"

    def get_target_type(self, obj):
        if obj.bot_group:
            return "bot_group"
        elif obj.bot:
            return "bot"
        return "unknown"

    def get_access_type(self, obj):
        if obj.bot_group:
            return "Bot Group"
        elif obj.bot:
            return "Bot"
        return "Unknown"

    def get_used(self, obj):
        try:
            return SubscriptionCodeAcceptance.objects.filter(subscription_code=obj).count()
        except Exception as e:
            logger.exception(f"Error counting subscription code usages: {str(e)}")
            return 0

class RedeemSubscriptionCodeSerializer(serializers.Serializer):
    access_code = serializers.CharField(max_length=255, required=True)

    def validate_access_code(self, value):
        """Validate that the subscription code exists and can be redeemed by this user"""
        if not value:
            raise serializers.ValidationError("Access code is required")

        try:
            subscription_code = SubscriptionCode.objects.get(code=value)
            user = self.context['request'].user

            # Check if user already redeemed this subscription code
            if SubscriptionCodeAcceptance.objects.filter(subscription_code=subscription_code, user=user).exists():
                raise serializers.ValidationError("You have already redeemed this access code")

            # Enforce limit for subscription codes (0 means no redemptions allowed)
            used = SubscriptionCodeAcceptance.objects.filter(subscription_code=subscription_code).count()
            if used >= subscription_code.limit:
                raise serializers.ValidationError("This access code has reached its redemption limit")

            # If professor already owns or collaborates on the target, do not allow redemption
            if user.is_creator:
                if subscription_code.bot:
                    bot = subscription_code.bot
                    owns_or_collabs = (
                        getattr(bot, 'user', None) == user or
                        (hasattr(bot, 'bot_group') and (
                            getattr(bot.bot_group, 'owner', None) == user or
                            bot.bot_group.collaborators.filter(id=user.id).exists()
                        ))
                    )
                    if owns_or_collabs:
                        raise serializers.ValidationError(
                            "You already own or manage this bot; no need to redeem an access code."
                        )
                if subscription_code.bot_group:
                    bot_group = subscription_code.bot_group
                    if bot_group.owner == user or bot_group.collaborators.filter(id=user.id).exists():
                        raise serializers.ValidationError(
                            "You already own or collaborate on this bot group; no need to redeem an access code."
                        )

            # Store the subscription code object for later use
            self._subscription_code = subscription_code
            return value
        except SubscriptionCode.DoesNotExist:
            raise serializers.ValidationError("Invalid access code. Please check with your instructor.")

    def save(self):
        """Redeem the subscription code for the authenticated user"""
        subscription_code = getattr(self, '_subscription_code', None)
        if not subscription_code:
            raise serializers.ValidationError("Access code validation failed")

        user = self.context['request'].user

        # Create subscription code acceptance record
        acceptance = SubscriptionCodeAcceptance.objects.create(
            subscription_code=subscription_code,
            user=user
        )

        # Determine target information and create appropriate message
        if subscription_code.bot_group:
            target_name = subscription_code.bot_group.title
            target_type = "bot_group"
            # Count bots in the bot group for informative message
            bot_count = subscription_code.bot_group.bots.count()
            if bot_count > 0:
                message = f'Access code redeemed successfully! You now have access to the bot group "{target_name}" and all {bot_count} bots within it.'
            else:
                message = f'Access code redeemed successfully! You now have access to the bot group "{target_name}".'
        elif subscription_code.bot:
            target_name = f"{subscription_code.bot.bot_group.title} - {subscription_code.bot.title}"
            target_type = "bot"
            message = f'Access code redeemed successfully! You now have access to: {target_name}'
        else:
            target_name = "Unknown"
            target_type = "unknown"
            message = f'Access code redeemed successfully! You now have access to: {target_name}'

        return {
            'message': message,
            'target_name': target_name,
            'target_type': target_type,
            'redeemed_at': acceptance.created_at.isoformat()
        }

class RedeemSuccessSerializer(serializers.Serializer):
    message = serializers.CharField()
    target_name = serializers.CharField()
    target_type = serializers.CharField()
    redeemed_at = serializers.CharField()

class RegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    access_code = serializers.CharField(max_length=255, required=True)

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match")

        return data

    def validate_access_code(self, value):
        """
        Validate access code against DARE (required) and optionally SB (soft check).

        Primary validation: DARE AccessCodeGroup - assigns platform_role during registration
        Soft check: SB SubscriptionCode - if matching code exists, auto-subscribe to bot/bot group

        The DARE access code is REQUIRED for registration.
        The SB subscription code is optional - if it exists and has capacity, user gets subscribed.
        """
        if not value:
            raise serializers.ValidationError("Access code is required for registration")

        # Track what we found
        self._dare_access_code = None
        self._subscription_code = None
        self._voice_match = None

        # A code may name a bot (board code) or a voice assignment, never both:
        # they would demand different roles, so the collision is refused outright.
        board_code = SubscriptionCode.objects.filter(code=value).first()
        try:
            voice_match = resolve_voice_signup_code(value)
        except VoiceAccessCodeError as exc:
            raise serializers.ValidationError(str(exc))
        if board_code and voice_match:
            raise serializers.ValidationError(
                "This code is assigned to both a chat bot and a voice assignment and cannot be "
                "used to sign up. Ask your instructor for a distinct code."
            )
        if voice_match:
            # Mirror the code into DARE as a RESEARCHER registration code so the
            # standard DARE checks below (and DARE registration) assign the role.
            try:
                ensure_signup_code_in_dare(value)
            except VoiceAccessCodeError as exc:
                raise serializers.ValidationError(str(exc))

        # Primary check: DARE backend for role-based access code (REQUIRED)
        # NOTE: DARE uses djangorestframework-camelcase, so keys come back as camelCase
        try:
            dare_check = auth_client.check_access_code_exists(value)
            logger.info(f"DARE access code check result: {dare_check}")

            if dare_check.get('exists') is True:
                # Handle both camelCase (from DARE) and snake_case (fallback)
                available_slots = dare_check.get('availableSlots') or dare_check.get('available_slots') or 0
                default_role = dare_check.get('defaultRole') or dare_check.get('default_role')

                logger.info(f"Parsed DARE response - availableSlots: {available_slots}, defaultRole: {default_role}")

                provisioned_by = dare_check.get('provisionedBy') or dare_check.get('provisioned_by')
                if provisioned_by == VOICE_PROVISIONER and not voice_match:
                    # DARE still holds the code but no live assignment uses it any more.
                    raise serializers.ValidationError(
                        "This voice assignment code is no longer active. Ask your instructor for a current code."
                    )

                # Check if code is actually available (not expired, not at limit)
                if isinstance(available_slots, int) and available_slots > 0:
                    self._dare_access_code = value
                    logger.info(f"DARE access code VALID: {value}, role: {default_role}, slots: {available_slots}")
                else:
                    # DARE code exists but is not available
                    error_msg = dare_check.get('message', 'Access code is not available')
                    logger.warning(f"DARE access code {value} exists but NOT available (slots={available_slots}): {error_msg}")
                    raise serializers.ValidationError(error_msg)
            else:
                logger.info(f"DARE access code {value} does not exist (exists={dare_check.get('exists')})")
        except serializers.ValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            logger.exception(f"Error checking DARE access code: {e}")

        # DARE access code is required
        if not self._dare_access_code:
            raise serializers.ValidationError("Invalid access code. Please check with your instructor.")

        self._voice_match = voice_match

        # Soft check: SB subscription codes for bot/bot group access (OPTIONAL bonus)
        try:
            subscription_code = SubscriptionCode.objects.get(code=value)
            # Only subscribe if there's capacity (soft check - don't fail if at limit)
            used = SubscriptionCodeAcceptance.objects.filter(subscription_code=subscription_code).count()
            if used < subscription_code.limit:
                self._subscription_code = subscription_code
                logger.info(f"Found matching SB subscription code: {value} - will auto-subscribe")
            else:
                logger.info(f"SB subscription code {value} exists but at limit - skipping auto-subscribe")
        except SubscriptionCode.DoesNotExist:
            logger.info(f"No matching SB subscription code for {value} - that's fine")

        return value

    def create(self, validated_data):
        """
        Create user in DARE backend and handle local user creation.

        - DARE access code is REQUIRED and passed to DARE for role assignment
        - SB subscription code is OPTIONAL - if found, auto-subscribe to bot/bot group
        """
        # Remove confirm_password as it's not needed for DARE
        validated_data.pop('confirm_password', None)

        # Get validated access codes
        dare_access_code = getattr(self, '_dare_access_code', None)
        subscription_code = getattr(self, '_subscription_code', None)
        voice_match = getattr(self, '_voice_match', None)
        voice_agents = voice_match.agents if voice_match else []

        # DARE access code is required (validated in validate_access_code)
        if not dare_access_code:
            raise serializers.ValidationError("Access code validation failed")

        # Prepare data for DARE backend with access code for role assignment.
        # The role itself is never sent: DARE derives it from the access code.
        dare_data = {
            'email': validated_data['email'],
            'password1': validated_data['password'],
            'password2': validated_data['password'],
            'name': validated_data['name'],
            'access_code': dare_access_code,
        }

        try:
            # Use centralized DARE API client for registration
            auth_client.register_user(dare_data)
        except DareApiError as e:
            # The centralized error handler has already parsed the error message
            raise serializers.ValidationError(e.message)

        # DARE now owns the account. Local provisioning is one transaction and is
        # safe to repeat: a stale local shell for the same email is reused and
        # every grant is get_or_create.
        try:
            with transaction.atomic():
                local_user = self._get_or_create_local_user(validated_data)
                if subscription_code:
                    SubscriptionCodeAcceptance.objects.get_or_create(
                        subscription_code=subscription_code,
                        user=local_user,
                    )
                if voice_agents:
                    grant_voice_access(local_user, voice_agents)
        except Exception:
            logger.exception("Local provisioning failed after DARE registration succeeded")
            raise serializers.ValidationError(
                "Your account was created, but we could not finish setting up your access. "
                "Verify your email, sign in, and enter your access code under Voice Assignments "
                "or Access Codes to unlock it."
            )

        content_info = ''
        if subscription_code:
            # Prepare content-specific info for subscription codes
            if subscription_code.bot_group:
                bot_count = subscription_code.bot_group.bots.count()
                if bot_count > 0:
                    content_info = f' You have access to the bot group "{subscription_code.bot_group.title}" and all {bot_count} bots within it.'
                else:
                    content_info = f' You have access to the bot group "{subscription_code.bot_group.title}".'
            elif subscription_code.bot:
                content_info = f' You have access to the bot "{subscription_code.bot.title}" in the bot group "{subscription_code.bot.bot_group.title}".'
        elif len(voice_agents) == 1:
            content_info = f' You have access to the voice assignment "{voice_agents[0].name}".'
        elif voice_agents:
            content_info = f' You have access to {len(voice_agents)} voice assignments.'

        if voice_agents:
            base_message = (
                f'Welcome to SocraticBots, {local_user.name}! Your researcher account has been created successfully.'
            )
            next_steps = [
                'Check your email for a confirmation link from DARE',
                'Click the confirmation link to activate your account',
                'Sign in to SocraticBots to open your voice assignment',
                'Create your own voice agents from the Voice Assignments page',
            ]
        else:
            base_message = f'Welcome to SocraticBots, {local_user.name}! Your account has been created successfully.'
            next_steps = [
                'Check your email for a confirmation link from DARE',
                'Click the confirmation link to activate your account',
                'Return to SocraticBots to get started',
            ]

        return {
            'message': base_message + content_info,
            'name': local_user.name,
            'user_type': 'researcher' if voice_agents else 'user',
            'next_steps': next_steps,
            'has_dual_access': True,  # Always true now since DARE code is required
            'has_bot_access': subscription_code is not None,  # True if also got SB subscription
            'has_voice_access': bool(voice_agents),
            'voice_assignments': [
                {'id': agent.id, 'name': agent.name, 'exam_title': agent.exam_title}
                for agent in voice_agents
            ],
            'platforms': ['SocraticBots']
        }

    @staticmethod
    def _get_or_create_local_user(validated_data):
        # DARE lower-cases the email; the login sync looks the local user up by
        # that form, so create it the same way to avoid a second local account.
        email = validated_data['email'].lower()
        local_user = CustomUser.objects.filter(email__iexact=email).first()
        if local_user is None:
            local_user = CustomUser.objects.create_user(
                email=email,
                name=validated_data['name'],
                password=validated_data['password'],
            )
        return local_user

class VoiceAssignmentSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    exam_title = serializers.CharField(allow_blank=True)

class RegistrationSuccessSerializer(serializers.Serializer):
    message = serializers.CharField()
    name = serializers.CharField()
    user_type = serializers.CharField()
    next_steps = serializers.ListField(child=serializers.CharField())
    has_dual_access = serializers.BooleanField()
    has_bot_access = serializers.BooleanField(required=False, default=False)
    has_voice_access = serializers.BooleanField(required=False, default=False)
    voice_assignments = VoiceAssignmentSummarySerializer(many=True, required=False, default=list)
    platforms = serializers.ListField(child=serializers.CharField())
