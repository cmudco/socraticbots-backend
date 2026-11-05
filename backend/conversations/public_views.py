"""
Public conversation views for anonymous access to public bots.
No authentication required.
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from bots.models import Bot
from bots.serializers import BotDetailSerializer
from utils.dare_api.conversations import get_conversations_client
from utils.dare_api.base import DareApiError

import logging

logger = logging.getLogger(__name__)


class PublicBotViewSet(viewsets.ViewSet):
    """
    ViewSet for public bot operations (no authentication required)
    """
    permission_classes = []  # No authentication required
    authentication_classes = []  # No authentication required

    @action(detail=True, methods=['get'], url_path='info')
    def get_info(self, request, pk=None):
        """
        Get complete public bot information (no authentication required).
        Returns full bot details including model preferences, prompts, files, etc.
        Same data structure as authenticated bot endpoint.
        """
        try:
            bot = get_object_or_404(Bot, id=pk)

            if not bot.is_publicly_deployed:
                return Response({
                    'error': 'This bot is not publicly available'
                }, status=status.HTTP_403_FORBIDDEN)

            # Use the same detailed serializer as authenticated endpoint
            serializer = BotDetailSerializer(bot)
            return Response(serializer.data)

        except Bot.DoesNotExist:
            return Response({
                'error': 'Bot not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Unexpected error getting public bot info: {str(e)}")
            return Response({
                'error': 'An unexpected error occurred'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='conversations')
    def get_or_create_conversation(self, request, pk=None):
        """
        Get or create a conversation for a public bot (no authentication required).

        Request body:
            {
                "sessionId": "unique-browser-session-id"
            }

        Returns:
            {
                "dareConversationId": "abc123",
                "botId": 1,
                "botName": "Physics Tutor"
            }
        """
        try:
            # Get session ID from request (DRF converts camelCase to snake_case)
            session_id = request.data.get('session_id') or request.data.get('sessionId')
            if not session_id:
                return Response({
                    'error': 'sessionId is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Get the bot and verify it's publicly deployed
            bot = get_object_or_404(Bot, id=pk)

            if not bot.is_publicly_deployed:
                return Response({
                    'code': 'NOT_PUBLIC',
                    'message': 'This bot is not publicly available',
                }, status=status.HTTP_403_FORBIDDEN)

            if not bot.is_active:
                return Response({
                    'code': 'BOT_INACTIVE',
                    'message': 'This bot is currently inactive',
                }, status=status.HTTP_403_FORBIDDEN)

            if bot.budget is None or bot.budget <= 0:
                return Response({
                    'code': 'BOT_CAP_REACHED',
                    'message': (
                        'This bot is not configured for public use '
                        '(missing budget cap). Please contact the creator.'
                    ),
                }, status=status.HTTP_402_PAYMENT_REQUIRED)

            if bot.budget_used >= bot.budget:
                return Response({
                    'code': 'BOT_CAP_REACHED',
                    'message': (
                        'This bot has reached its usage cap. Please try again '
                        'later or contact the creator.'
                    ),
                    'budgetUsed': str(bot.budget_used),
                    'budget': str(bot.budget),
                }, status=status.HTTP_402_PAYMENT_REQUIRED)

            # For public bots, we need to use a system token or create temp token
            # For now, we'll use None and update DARE to allow anonymous conversation creation
            dare_api = get_conversations_client(token=None)

            # Query DARE backend for existing conversation with this bot_id + session_id
            try:
                conversations = dare_api.get_conversations_by_bot_id(
                    bot_id=pk,
                    anonymous_session_id=session_id
                )

                if conversations and len(conversations) > 0:
                    # Found existing conversation
                    conversation = conversations[0]
                    conversation_id = conversation.get('conversationId')

                    logger.info(f"Found existing public conversation {conversation_id} for bot {pk} and session {session_id}")

                    return Response({
                        'dareConversationId': conversation_id,
                        'botId': bot.id,
                        'botName': bot.title
                    })
                else:
                    # No existing conversation, create new one
                    logger.info(f"Creating new public conversation for bot {pk} and session {session_id}")

                    try:
                        # Create conversation in DARE with bot_id and session_id
                        created_conversation = dare_api.create_conversation(
                            bot_id=pk,
                            anonymous_session_id=session_id
                        )
                        conversation_id = created_conversation.get('conversationId')

                        return Response({
                            'dareConversationId': conversation_id,
                            'botId': bot.id,
                            'botName': bot.title
                        }, status=status.HTTP_201_CREATED)

                    except DareApiError as create_error:
                        logger.error(f"DARE API error creating public conversation: {create_error.message}")
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
            logger.error(f"Unexpected error in public conversation setup: {str(e)}")
            return Response({
                'error': 'An unexpected error occurred'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
