from django.shortcuts import render, get_object_or_404
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import SubscriptionCode, SubscriptionCodeAcceptance
from .serializers import RegistrationSerializer, RegistrationSuccessSerializer, SubscriptionCodeSerializer, RedeemSubscriptionCodeSerializer, RedeemSuccessSerializer
from users.authentication import JWTAuthentication
from utils.dare_api import auth_client, DareApiError
from bots.models import Bot, BotGroup
from voice.access_codes import live_agents_for_code
import string
import random

# Create your views here.

@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Register a new user in SocraticBots with access code validation.
    This endpoint will validate the access code and create users in both DARE and SocraticBots.
    The user type (student or creator) is determined by the DARE platform_role in the JWT token.
    """
    serializer = RegistrationSerializer(data=request.data)

    if serializer.is_valid():
        try:
            result = serializer.save()
            success_serializer = RegistrationSuccessSerializer(result)
            return Response(success_serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response({
                'error': 'Registration failed',
                'detail': _validation_message(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'error': 'Registration failed',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def _validation_message(error):
    """Flatten a DRF ValidationError into one user-facing sentence."""
    detail = error.detail
    if isinstance(detail, dict):
        detail = [item for values in detail.values() for item in (values if isinstance(values, list) else [values])]
    if isinstance(detail, list):
        return ' '.join(str(item) for item in detail)
    return str(detail)

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def redeem_access_code(request):
    """
    Redeem an access code for an authenticated user (student or professor).
    Professor registration codes remain non-redeemable post-registration and are
    validated in the serializer. Bot and Bot Group access codes are redeemable
    by both roles.
    """
    serializer = RedeemSubscriptionCodeSerializer(data=request.data, context={'request': request})

    if serializer.is_valid():
        try:
            result = serializer.save()
            success_serializer = RedeemSuccessSerializer(result)
            return Response(success_serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                'error': 'Failed to redeem access code',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

def generate_unique_code():
    """Generate a unique subscription code"""
    while True:
        # Generate a code like "SB-ABC123XY"
        code = "SB-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        # Check if code already exists
        if not SubscriptionCode.objects.filter(code=code).exists():
            return code

@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_professor_access_code(request):
    """
    DEPRECATED: Professor/creator registration codes are now managed exclusively
    through DARE backend. This endpoint returns an informative error.
    """
    return Response(
        {'error': 'Professor registration codes are now managed through the DARE admin panel. '
                  'Please create an access code with the CREATOR role in DARE.'},
        status=status.HTTP_410_GONE
    )

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def list_user_access_codes(request):
    """
    List all access codes that the current authenticated user has redeemed/used.
    Available for both students and professors.
    """
    user = request.user

    try:
        # Get all subscription code acceptances for this user
        acceptances = (
            SubscriptionCodeAcceptance.objects
            .filter(user=user)
            .select_related('subscription_code', 'subscription_code__bot', 'subscription_code__bot_group')
        )

        # Build the response data
        redeemed_codes = []
        for acceptance in acceptances:
            access_code = acceptance.subscription_code

            # Determine target information
            if access_code.bot:
                target_name = f"{access_code.bot.bot_group.title} - {access_code.bot.title}"
                target_type = "bot"
            elif access_code.bot_group:
                target_name = access_code.bot_group.title
                target_type = "bot_group"
            else:
                target_name = "Unknown"
                target_type = "unknown"

            redeemed_codes.append({
                'code': access_code.code,
                'target_name': target_name,
                'target_type': target_type,
                'redeemed_at': acceptance.created_at.isoformat(),
                'access_code_created_at': access_code.created_at.isoformat(),
            })

        return Response({
            'redeemed_codes': redeemed_codes,
            'total_count': len(redeemed_codes)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'error': 'Failed to retrieve redeemed access codes',
            'detail': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def generate_bot_access_code(request, bot_group_id, bot_id):
    """
    Generate or update an access code for a specific bot.
    Only professors who own or collaborate on the bot group can generate access codes.
    """
    user = request.user
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can generate bot access codes'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Get the bot and verify permissions
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to generate access codes for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get custom code from request or generate one
        custom_code = request.data.get('code', '').strip()
        limit_raw = request.data.get('limit', None)
        limit_value = None
        if limit_raw is not None:
            try:
                limit_value = int(limit_raw) if limit_raw != '' else 0
            except (TypeError, ValueError):
                limit_value = None
        
        if custom_code:
            # Check if custom code already exists (as a bot code or a live voice assignment code)
            if (
                SubscriptionCode.objects.filter(code=custom_code).exclude(bot=bot).exists()
                or live_agents_for_code(custom_code).exists()
            ):
                return Response(
                    {'error': 'This access code is already in use'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            code = custom_code
        else:
            # Generate unique code
            code = generate_unique_code()

        # Check if bot already has an access code
        existing_access_code = SubscriptionCode.objects.filter(bot=bot).first()
        
        if existing_access_code:
            # Update existing access code
            existing_access_code.code = code
            if limit_value is not None:
                existing_access_code.limit = limit_value
            existing_access_code.save()
            access_code = existing_access_code
        else:
            # Create new access code
            access_code = SubscriptionCode.objects.create(
                code=code,
                bot=bot,
                created_by=user,
                limit=(limit_value if limit_value is not None else 0)
            )

        # Serialize and return the access code
        serializer = SubscriptionCodeSerializer(access_code)

        # Sync to DARE
        user_token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
        auth_client.sync_access_code_to_dare(
            user_token=user_token,
            access_code=access_code.code,
            max_capacity=access_code.limit,
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': 'Failed to generate bot access code', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_access_code(request, bot_group_id, bot_id):
    """
    Get the access code for a specific bot.
    Only professors who own or collaborate on the bot group can view access codes.
    """
    user = request.user
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can view bot access codes'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Get the bot and verify permissions
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to view access codes for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get the access code for this bot
        access_code = SubscriptionCode.objects.filter(bot=bot).first()
        
        if access_code:
            serializer = SubscriptionCodeSerializer(access_code)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {'error': 'No access code found for this bot'},
                status=status.HTTP_404_NOT_FOUND
            )

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': 'Failed to retrieve bot access code', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def delete_bot_access_code(request, bot_group_id, bot_id):
    """
    Delete the access code for a specific bot.
    Only professors who own or collaborate on the bot group can delete access codes.
    """
    user = request.user
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can delete bot access codes'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Get the bot and verify permissions
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to delete access codes for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get and delete the access code for this bot
        access_code = SubscriptionCode.objects.filter(bot=bot).first()
        
        if access_code:
            # Deactivate in DARE before deleting locally
            user_token = request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
            auth_client.sync_access_code_to_dare(
                user_token=user_token,
                access_code=access_code.code, action="delete"
            )
            access_code.delete()
            return Response(
                {'message': 'Bot access code deleted successfully'},
                status=status.HTTP_204_NO_CONTENT
            )
        else:
            return Response(
                {'error': 'No access code found for this bot'},
                status=status.HTTP_404_NOT_FOUND
            )

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': 'Failed to delete bot access code', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_access_users(request, bot_group_id, bot_id):
    """
    Get all users who have access to a specific bot.
    Only professors who own or collaborate on the bot group can view this information.
    """
    user = request.user
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can view bot access users'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to view access users for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        all_access_users = []
        seen_users = set()

        # 1. Bot creator
        if bot.user.id not in seen_users:
            seen_users.add(bot.user.id)
            all_access_users.append({
                'user_id': bot.user.id,
                'email': bot.user.email,
                'first_name': getattr(bot.user, 'first_name', ''),
                'last_name': getattr(bot.user, 'last_name', ''),
                'access_type': 'bot_creator',
                'access_code': 'N/A',
                'access_granted_at': bot.created_at.isoformat(),
                'is_creator': getattr(bot.user, 'is_creator', False)
            })

        # 2. Bot group owner
        if bot_group.owner.id not in seen_users:
            seen_users.add(bot_group.owner.id)
            all_access_users.append({
                'user_id': bot_group.owner.id,
                'email': bot_group.owner.email,
                'first_name': getattr(bot_group.owner, 'first_name', ''),
                'last_name': getattr(bot_group.owner, 'last_name', ''),
                'access_type': 'bot_group_owner',
                'access_code': 'N/A',
                'access_granted_at': bot_group.created_at.isoformat(),
                'is_creator': getattr(bot_group.owner, 'is_creator', False)
            })

        # 3. Bot group collaborators
        for collaborator in bot_group.collaborators.all():
            if collaborator.id not in seen_users:
                seen_users.add(collaborator.id)
                all_access_users.append({
                    'user_id': collaborator.id,
                    'email': collaborator.email,
                    'first_name': getattr(collaborator, 'first_name', ''),
                    'last_name': getattr(collaborator, 'last_name', ''),
                    'access_type': 'bot_group_collaborator',
                    'access_code': 'N/A',
                    'access_granted_at': bot_group.created_at.isoformat(),
                    'is_creator': getattr(collaborator, 'is_creator', False)
                })

        # 4. Users with direct bot access codes
        bot_access_acceptances = SubscriptionCodeAcceptance.objects.filter(
            subscription_code__bot=bot
        ).select_related('user', 'subscription_code')
        
        for acceptance in bot_access_acceptances:
            if acceptance.user.id not in seen_users:
                seen_users.add(acceptance.user.id)
                all_access_users.append({
                    'user_id': acceptance.user.id,
                    'email': acceptance.user.email,
                    'first_name': getattr(acceptance.user, 'first_name', ''),
                    'last_name': getattr(acceptance.user, 'last_name', ''),
                    'access_type': 'direct_bot',
                    'access_code': acceptance.subscription_code.code,
                    'access_granted_at': acceptance.created_at.isoformat(),
                    'is_creator': getattr(acceptance.user, 'is_creator', False)
                })

        # 5. Users with bot group access codes
        bot_group_access_acceptances = SubscriptionCodeAcceptance.objects.filter(
            subscription_code__bot_group=bot_group
        ).select_related('user', 'subscription_code')
        
        for acceptance in bot_group_access_acceptances:
            if acceptance.user.id not in seen_users:
                seen_users.add(acceptance.user.id)
                all_access_users.append({
                    'user_id': acceptance.user.id,
                    'email': acceptance.user.email,
                    'first_name': getattr(acceptance.user, 'first_name', ''),
                    'last_name': getattr(acceptance.user, 'last_name', ''),
                    'access_type': 'bot_group',
                    'access_code': acceptance.subscription_code.code,
                    'access_granted_at': acceptance.created_at.isoformat(),
                    'is_creator': getattr(acceptance.user, 'is_creator', False)
                })

        all_access_users.sort(key=lambda x: x['access_granted_at'], reverse=True)
        return Response({
            'bot_id': bot.id,
            'bot_title': bot.title,
            'bot_group_id': bot_group.id,
            'bot_group_title': bot_group.title,
            'access_users': all_access_users,
            'total_count': len(all_access_users)
        }, status=status.HTTP_200_OK)

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': 'Failed to retrieve bot access users', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def remove_user_bot_access(request, bot_group_id, bot_id, user_id):
    """
    Remove a user's access to a specific bot by deleting their access code acceptance.
    Only professors who own or collaborate on the bot group can remove access.
    """
    user = request.user
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can remove bot access'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to remove access for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        User = get_user_model()
        target_user = get_object_or_404(User, id=user_id)

        if bot_group.owner == target_user:
            return Response({
                'error': 'Cannot remove access for the bot group owner'
            }, status=status.HTTP_400_BAD_REQUEST)

        if bot.user == target_user:
            return Response({
                'error': 'Cannot remove access for the bot creator'
            }, status=status.HTTP_400_BAD_REQUEST)

        deleted_count = 0
        removed_access_types = []

        bot_access_acceptances = SubscriptionCodeAcceptance.objects.filter(
            subscription_code__bot=bot,
            user=target_user
        )
        if bot_access_acceptances.exists():
            deleted_count += bot_access_acceptances.count()
            removed_access_types.append('direct_bot')
            bot_access_acceptances.delete()

        bot_group_access_acceptances = SubscriptionCodeAcceptance.objects.filter(
            subscription_code__bot_group=bot_group,
            user=target_user
        )
        if bot_group_access_acceptances.exists():
            deleted_count += bot_group_access_acceptances.count()
            removed_access_types.append('bot_group')
            bot_group_access_acceptances.delete()

        if bot_group.collaborators.filter(id=target_user.id).exists():
            bot_group.collaborators.remove(target_user)
            removed_access_types.append('bot_group_collaborator')

        if deleted_count > 0 or 'bot_group_collaborator' in removed_access_types:
            return Response({
                'message': f'Successfully removed access for user {target_user.email}',
                'deleted_acceptances': deleted_count,
                'removed_access_types': removed_access_types
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': 'User does not have removable access to this bot'
            }, status=status.HTTP_404_NOT_FOUND)

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except User.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': 'Failed to remove user access', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
