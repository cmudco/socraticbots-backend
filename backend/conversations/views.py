"""
Simple conversation proxy views that work directly with DARE backend.
No local conversation models - just bot_id + user_id -> DARE conversation.
"""

from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from bots.models import Bot
from access_codes.models import SubscriptionCodeAcceptance
from users.authentication import JWTAuthentication
from users.models import CustomUser
from utils.dare_api.conversations import get_conversations_client
from utils.dare_api.base import DareApiError

import logging

logger = logging.getLogger(__name__)


def _check_bot_access(bot: Bot, user) -> bool:
    """
    Check if user has access to the bot via ownership or access codes.
    """
    # Check if user is owner/collaborator of bot group
    if (bot.bot_group.owner == user or 
        bot.bot_group.collaborators.filter(id=user.id).exists()):
        return True
    
    # Check if user has access via subscription codes
    # Direct bot group access
    bot_group_access = SubscriptionCodeAcceptance.objects.filter(
        user=user,
        subscription_code__bot_group=bot.bot_group
    ).exists()

    # Individual bot access
    individual_bot_access = SubscriptionCodeAcceptance.objects.filter(
        user=user,
        subscription_code__bot=bot
    ).exists()
    
    return bot_group_access or individual_bot_access


def _redeemed_access_code_for_bot(bot: Bot, user):
    """
    Return the access-code string the user redeemed for this bot, if any.

    Prefers a bot-level redemption; falls back to a bot-group-level
    redemption. Used to forward ``access_code`` to DARE so its billing
    finalizer can resolve the matching ``AccessCodeGroup`` (and its
    ``GroupWallet``) for any group-funded billing logic on its side.
    Returns ``None`` for owners/collaborators (they don't redeem) and for
    bots the user has no redemption against.
    """
    acceptance = (
        SubscriptionCodeAcceptance.objects
        .filter(user=user, subscription_code__bot=bot)
        .select_related("subscription_code")
        .first()
    )
    if acceptance is None:
        acceptance = (
            SubscriptionCodeAcceptance.objects
            .filter(user=user, subscription_code__bot_group=bot.bot_group)
            .select_related("subscription_code")
            .first()
        )
    return acceptance.subscription_code.code if acceptance else None


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_or_create_bot_conversation(request, bot_id):
    """
    Get or create a conversation for a specific bot and the authenticated user.
    Queries DARE backend by bot_id to find existing conversation, or creates new one.

    Returns:
        {
            "dareConversationId": "abc123",
            "botId": 1,
            "botName": "Physics Tutor"
        }
    """
    user = request.user

    try:
        # Get the bot and verify user has access
        bot = get_object_or_404(Bot, id=bot_id)

        if not _check_bot_access(bot, user):
            return Response({
                'error': 'You do not have access to this bot'
            }, status=status.HTTP_403_FORBIDDEN)

        # Get auth token for DARE API
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Invalid authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)

        dare_token = auth_header.split(' ')[1]
        dare_api = get_conversations_client(token=dare_token)

        # Query DARE backend for existing conversation with this bot_id
        try:
            conversations = dare_api.get_conversations_by_bot_id(bot_id)

            if conversations and len(conversations) > 0:
                # Found existing conversation for this bot+user combo
                conversation = conversations[0]  # Should only be one per bot+user
                conversation_id = conversation.get('conversationId')

                logger.info(f"Found existing DARE conversation {conversation_id} for bot {bot_id} and user {user.id}")

                return Response({
                    'dareConversationId': conversation_id,
                    'botId': bot.id,
                    'botName': bot.title
                })
            else:
                # No existing conversation, create new one
                logger.info(f"Creating new DARE conversation for bot {bot_id} and user {user.id}")

                try:
                    # Create conversation in DARE with bot_id (let DARE generate random ID).
                    # Forward the redeemed access code so DARE's billing finalizer can
                    # match it to an AccessCodeGroup -> GroupWallet without an SB callback.
                    access_code = _redeemed_access_code_for_bot(bot, user)
                    created_conversation = dare_api.create_conversation(
                        bot_id=bot_id,
                        access_code=access_code,
                    )
                    conversation_id = created_conversation.get('conversationId')

                    return Response({
                        'dareConversationId': conversation_id,
                        'botId': bot.id,
                        'botName': bot.title
                    }, status=status.HTTP_201_CREATED)

                except DareApiError as create_error:
                    logger.error(f"DARE API error creating conversation: {create_error.message}")
                    return Response({
                        'error': f'Failed to create conversation: {create_error.message}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except DareApiError as e:
            logger.error(f"DARE API error querying conversations: {e.message}")
            return Response({
                'error': f'Failed to query conversations: {e.message}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Bot.DoesNotExist:
        return Response({
            'error': 'Bot not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Unexpected error in conversation setup: {str(e)}")
        return Response({
            'error': 'An unexpected error occurred'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_conversation_messages(request, conversation_id):
    """
    Proxy endpoint to get conversation messages from DARE backend
    """
    # Get auth token for DARE API
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return Response({
            'error': 'Invalid authorization header'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    dare_token = auth_header.split(' ')[1]
    
    try:
        dare_api = get_conversations_client(token=dare_token)
        messages = dare_api.get_conversation_messages(conversation_id)
        return Response(messages)
        
    except DareApiError as e:
        return Response({
            'error': f'Failed to get messages: {e.message}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_available_models(request):
    """
    Proxy endpoint to get available LLM models from DARE backend
    """
    # Get auth token for DARE API
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return Response({
            'error': 'Invalid authorization header'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    dare_token = auth_header.split(' ')[1]
    
    try:
        dare_api = get_conversations_client(token=dare_token)
        models = dare_api.get_models()
        return Response(models)
        
    except DareApiError as e:
        return Response({
            'error': f'Failed to get models: {e.message}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def delete_conversation(request, conversation_id):
    """
    Delete a conversation and all its messages/learning progress from DARE backend.
    This is a proxy to the DARE backend delete endpoint.
    """
    try:
        # Get auth token for DARE API
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Invalid authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        dare_token = auth_header.split(' ')[1]
        
        # Forward delete request to DARE backend
        dare_api = get_conversations_client(token=dare_token)
        
        # Call DARE's delete conversation endpoint (destroy method from ModelViewSet)
        result = dare_api.delete_conversation(conversation_id)
        
        logger.info(f"Successfully deleted conversation {conversation_id} for user {request.user.id}")
        
        return Response({
            'success': True,
            'message': f'Conversation {conversation_id} and all associated data deleted successfully'
        })
        
    except DareApiError as e:
        logger.error(f"DARE API error deleting conversation {conversation_id}: {e}")
        return Response({
            'success': False,
            'error': f'DARE API error: {e.message}'
        }, status=e.status_code)
        
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        return Response({
            'success': False,
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def delete_message(request, message_id):
    """Delete a specific message from a conversation in DARE backend."""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Invalid authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        dare_token = auth_header.split(' ')[1]
        dare_api = get_conversations_client(token=dare_token)
        dare_api.delete_message(message_id)
        
        logger.info(f"Successfully deleted message {message_id} for user {request.user.id}")
        
        return Response({
            'success': True,
            'message': f'Message {message_id} deleted successfully'
        })
        
    except DareApiError as e:
        logger.error(f"DARE API error deleting message {message_id}: {e}")
        return Response({
            'success': False,
            'error': f'DARE API error: {e.message}'
        }, status=e.status_code)
        
    except Exception as e:
        logger.error(f"Error deleting message {message_id}: {e}")
        return Response({
            'success': False,
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def export_conversation_pdf(request, conversation_id):
    """Export conversation as PDF by proxying to DARE backend."""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response({'error': 'Invalid authorization header'}, status=status.HTTP_401_UNAUTHORIZED)
        
        dare_token = auth_header.split(' ')[1]
        dare_api = get_conversations_client(token=dare_token)
        
        pdf_response = dare_api.export_conversation_pdf(conversation_id)
        
        logger.info(f"Successfully exported conversation {conversation_id} for user {request.user.id}")
        
        return pdf_response
        
    except DareApiError as e:
        logger.error(f"DARE API error exporting conversation {conversation_id}: {e}")
        return Response({
            'success': False, 
            'error': f'DARE API error: {e.message}'
        }, status=e.status_code)
        
    except Exception as e:
        logger.error(f"Error exporting conversation {conversation_id}: {e}")
        return Response({
            'success': False,
            'error': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_user_bot_conversations(request, bot_group_id, bot_id, user_id):
    """
    Get a user's conversations for a specific bot.

    Only professors who own or collaborate on the bot group can access this endpoint.
    Uses the DARE internal API to fetch conversations for the specified user.

    Args:
        bot_group_id: ID of the bot group
        bot_id: ID of the bot
        user_id: ID of the user whose conversations to fetch

    Returns:
        List of conversations with conversationId, title, createdAt, messageCount
    """
    user = request.user

    # Only professors can view student conversations
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can view user conversations'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Verify bot exists and user has permission
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to view conversations for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Verify target user exists
        target_user = get_object_or_404(CustomUser, id=user_id)

        # Use external_user_id (DARE user ID), not Socratic user ID
        dare_user_id = target_user.external_user_id
        if not dare_user_id:
            logger.warning(f"User {user_id} has no external_user_id (DARE user ID)")
            return Response({
                'user_id': target_user.id,
                'user_email': target_user.email,
                'user_name': f"{target_user.first_name} {target_user.last_name}".strip() or target_user.email,
                'bot_id': bot_id,
                'bot_title': bot.title,
                'conversations': [],
                'total_count': 0,
            })

        # Fetch conversations from DARE using internal API
        dare_api = get_conversations_client()
        conversations = dare_api.get_user_conversations_for_bot(
            user_id=int(dare_user_id),
            bot_id=bot_id
        )

        logger.info(
            f"Professor {user.id} fetched {len(conversations)} conversations "
            f"for user {user_id}, bot {bot_id}"
        )

        return Response({
            'user_id': target_user.id,
            'user_email': target_user.email,
            'user_name': f"{target_user.first_name} {target_user.last_name}".strip() or target_user.email,
            'bot_id': bot_id,
            'bot_title': bot.title,
            'conversations': conversations,
            'total_count': len(conversations),
        })

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except CustomUser.DoesNotExist:
        return Response(
            {'error': 'User not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except DareApiError as e:
        logger.error(f"DARE API error fetching user conversations: {e.message}")
        return Response(
            {'error': f'Failed to fetch conversations: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error fetching user conversations: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_conversation_messages_readonly(request, bot_group_id, bot_id, conversation_id):
    """
    Get messages for a specific conversation (read-only professor view).

    Only professors who own or collaborate on the bot group can access this endpoint.
    Uses the DARE internal API to fetch messages.

    Args:
        bot_group_id: ID of the bot group
        bot_id: ID of the bot
        conversation_id: DARE conversation ID

    Returns:
        Conversation details with full message list
    """
    user = request.user

    # Only professors can view student conversations
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can view conversation messages'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Verify bot exists and user has permission
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to view this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Fetch conversation messages from DARE using internal API
        dare_api = get_conversations_client()
        conversation_data = dare_api.get_conversation_messages_internal(conversation_id)

        logger.info(
            f"Professor {user.id} viewed conversation {conversation_id} "
            f"({len(conversation_data.get('messages', []))} messages)"
        )

        return Response(conversation_data)

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except DareApiError as e:
        logger.error(f"DARE API error fetching conversation messages: {e.message}")
        return Response(
            {'error': f'Failed to fetch messages: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error fetching conversation messages: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([permissions.IsAuthenticated])
def get_anonymous_bot_conversations(request, bot_group_id, bot_id):
    """
    Get all anonymous conversations for a public bot.

    Only professors who own or collaborate on the bot group can access this endpoint.
    Uses the DARE internal API to fetch anonymous conversations.

    Args:
        bot_group_id: ID of the bot group
        bot_id: ID of the bot

    Returns:
        List of anonymous conversations with conversationId, createdAt, messageCount, sessionId
    """
    user = request.user

    # Only professors can view anonymous conversations
    if not user.is_creator:
        return Response(
            {'error': 'Only professors can view anonymous conversations'},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Verify bot exists and user has permission
        bot = get_object_or_404(Bot, id=bot_id, bot_group__id=bot_group_id)
        bot_group = bot.bot_group

        # Check if user owns or collaborates on the bot group
        if bot_group.owner != user and not bot_group.collaborators.filter(id=user.id).exists():
            return Response(
                {'error': 'You do not have permission to view conversations for this bot'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get auth token for DARE API
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response({
                'error': 'Invalid authorization header'
            }, status=status.HTTP_401_UNAUTHORIZED)

        dare_token = auth_header.split(' ')[1]

        # Fetch anonymous conversations from DARE using professor's token
        dare_api = get_conversations_client(token=dare_token)
        conversations = dare_api.get_anonymous_conversations_for_bot(bot_id=bot_id)

        logger.info(
            f"Professor {user.id} fetched {len(conversations)} anonymous conversations "
            f"for bot {bot_id}"
        )

        return Response({
            'bot_id': bot_id,
            'bot_title': bot.title,
            'conversations': conversations,
            'total_count': len(conversations),
        })

    except Bot.DoesNotExist:
        return Response(
            {'error': 'Bot not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    except DareApiError as e:
        logger.error(f"DARE API error fetching anonymous conversations: {e.message}")
        return Response(
            {'error': f'Failed to fetch conversations: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error fetching anonymous conversations: {e}")
        return Response(
            {'error': 'Internal server error'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )