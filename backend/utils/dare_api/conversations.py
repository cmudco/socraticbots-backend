"""
DARE API client for conversation management
"""

import logging
from typing import Dict, Any, List, Optional

import requests
from django.conf import settings
from django.http import HttpResponse

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


class DareConversationsClient(BaseDareApiClient):
    """
    Client for DARE conversation API endpoints
    """
    
    def __init__(self, token: str = None):
        super().__init__()
        self.token = token
    
    def create_conversation(
        self,
        conversation_id: str = None,
        bot_id: int = None,
        anonymous_session_id: str = None,
        access_code: str = None,
    ) -> Dict[str, Any]:
        """
        Create a new conversation in DARE backend

        Args:
            conversation_id: Optional custom conversation ID for deterministic creation
            bot_id: Optional Socratic Bot ID (for SocraticBots source)
            anonymous_session_id: Optional session ID for anonymous public bot conversations
            access_code: Access-code string the user redeemed for this bot, if any.
                Forwarded so DARE can resolve the matching AccessCodeGroup
                (and its GroupWallet) for any group-funded billing logic on
                its side. Null for owner-funded or anonymous flows.

        Returns:
            Dictionary with conversation details including conversationId
        """
        try:
            url = f"{self.base_url}/api/conversations/"
            headers = self._get_headers(self.token)

            # Prepare request data
            data = {}
            if conversation_id:
                data['conversationId'] = conversation_id
            if bot_id:
                data['botId'] = bot_id
            if anonymous_session_id:
                data['anonymousSessionId'] = anonymous_session_id
            if access_code:
                data['accessCode'] = access_code

            logger.info(
                "Creating conversation in DARE backend at %s with ID: %s, "
                "bot_id: %s, session: %s, access_code: %s",
                url, conversation_id, bot_id, anonymous_session_id,
                access_code,
            )

            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 201:
                conversation_data = response.json()
                created_id = conversation_data.get('conversationId', conversation_id)
                logger.info(f"Successfully created DARE conversation: {created_id}")
                return conversation_data
            else:
                error_msg = self._parse_dare_error(response)
                logger.error(f"Failed to create conversation: {error_msg}")
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Request error creating conversation: {str(e)}")
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def create_conversation_with_id(self, conversation_id: str) -> Dict[str, Any]:
        """
        Create a conversation with a specific ID (alias for create_conversation with ID)
        
        Args:
            conversation_id: Custom conversation ID for deterministic creation
            
        Returns:
            Dictionary with conversation details including conversationId
        """
        return self.create_conversation(conversation_id=conversation_id)
    
    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """
        Get conversation details from DARE backend
        
        Args:
            conversation_id: DARE conversation ID
            
        Returns:
            Dictionary with conversation details
        """
        try:
            url = f"{self.base_url}/api/conversations/{conversation_id}/"
            headers = self._get_headers(self.token)
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def get_conversation_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        """
        Get messages for a conversation from DARE backend
        
        Args:
            conversation_id: DARE conversation ID
            
        Returns:
            List of message dictionaries
        """
        try:
            # Note: This endpoint might need to be adjusted based on DARE's actual API
            url = f"{self.base_url}/api/conversations/{conversation_id}/messages/"
            headers = self._get_headers(self.token)
            
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def update_conversation(self, conversation_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update conversation settings in DARE backend
        
        Args:
            conversation_id: DARE conversation ID
            updates: Dictionary of fields to update
            
        Returns:
            Updated conversation data
        """
        try:
            url = f"{self.base_url}/api/conversations/{conversation_id}/"
            headers = self._get_headers(self.token)
            
            response = requests.patch(url, headers=headers, json=updates)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete conversation in DARE backend
        
        Args:
            conversation_id: DARE conversation ID
            
        Returns:
            True if successful
        """
        try:
            url = f"{self.base_url}/api/conversations/{conversation_id}/"
            headers = self._get_headers(self.token)
            
            response = requests.delete(url, headers=headers)
            
            if response.status_code == 204:
                return True
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def delete_message(self, message_id: str) -> bool:
        """Soft-delete a message in DARE so it drops out of the conversation history."""
        try:
            url = f"{self.base_url}/api/messages/{message_id}/soft-delete/"
            headers = self._get_headers(self.token)

            response = requests.post(url, headers=headers)

            if response.status_code == 200:
                return True
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")

    def export_conversation_pdf(self, conversation_id: str):
        """Export conversation as PDF from DARE backend."""
        try:
            url = f"{self.base_url}/api/conversations/{conversation_id}/export-pdf/"
            headers = self._get_headers(self.token)
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                http_response = HttpResponse(
                    response.content, 
                    content_type='application/pdf'
                )
                http_response['Content-Disposition'] = response.headers.get('Content-Disposition', f'attachment; filename="conversation_{conversation_id}.pdf"')
                return http_response
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(message=error_msg, status_code=response.status_code)
        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")
    
    def get_conversations_by_bot_id(self, bot_id: int, anonymous_session_id: str = None) -> List[Dict[str, Any]]:
        """
        Get conversations for a specific bot_id from DARE backend

        Args:
            bot_id: Socratic Bot ID to filter by
            anonymous_session_id: Optional session ID for anonymous public bot conversations

        Returns:
            List of conversations associated with this bot_id (and session if provided)
        """
        try:
            url = f"{self.base_url}/api/conversations/"
            headers = self._get_headers(self.token)
            params = {'bot_id': bot_id}

            if anonymous_session_id:
                params['anonymous_session_id'] = anonymous_session_id

            logger.info(f"Querying DARE conversations with bot_id={bot_id}, session={anonymous_session_id}")

            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                # DARE returns {results: [...]} format or direct list
                conversations = data.get('results', data) if isinstance(data, dict) else data
                logger.info(f"Found {len(conversations)} conversations for bot_id={bot_id}")
                return conversations
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")

    def get_user_conversations_for_bot(self, user_id: int, bot_id: int) -> List[Dict[str, Any]]:
        """
        Fetch a user's conversations for a specific bot using internal service key.

        This method uses the DARE_INTERNAL_KEY for service-to-service authentication,
        allowing professors to view student conversations without needing the student's JWT.

        Args:
            user_id: DARE user ID to fetch conversations for
            bot_id: Socratic Bot ID to filter by

        Returns:
            List of conversation dictionaries with conversationId, title, createdAt, messageCount, botId
        """
        try:
            url = f"{self.base_url}/api/internal/user-conversations/"
            headers = {
                'Content-Type': 'application/json',
                'X-Internal-Key': getattr(settings, 'DARE_INTERNAL_KEY', ''),
            }
            params = {
                'user_id': user_id,
                'bot_id': bot_id,
            }

            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                conversations = data.get('conversations', [])
                return conversations
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")

    def get_conversation_messages_internal(self, conversation_id: str) -> Dict[str, Any]:
        """
        Fetch messages for a specific conversation using internal service key.

        This method uses the DARE_INTERNAL_KEY for service-to-service authentication,
        allowing professors to view student conversation messages.

        Args:
            conversation_id: DARE conversation ID

        Returns:
            Dict with conversationId, title, messages list, and totalCount
        """
        try:
            url = f"{self.base_url}/api/internal/conversations/{conversation_id}/messages/"
            headers = {
                'Content-Type': 'application/json',
                'X-Internal-Key': getattr(settings, 'DARE_INTERNAL_KEY', ''),
            }

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                return response.json()
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")

    def get_anonymous_conversations_for_bot(self, bot_id: int) -> List[Dict[str, Any]]:
        """
        Fetch all anonymous conversations for a specific bot using JWT authentication.

        This method uses the professor's JWT token for authentication,
        allowing professors to view anonymous public bot conversations.

        Args:
            bot_id: Socratic Bot ID to filter by

        Returns:
            List of conversation dictionaries with conversationId, createdAt, messageCount, sessionId
        """
        try:
            url = f"{self.base_url}/api/anonymous-conversations/"
            headers = self._get_headers(self.token)
            params = {
                'bot_id': bot_id,
            }

            response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                conversations = data.get('conversations', [])
                return conversations
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")

    def get_models(self) -> List[Dict[str, Any]]:
        """
        Get available LLM models from DARE backend

        Returns:
            List of available models
        """
        try:
            url = f"{self.base_url}/api/llms/"
            headers = self._get_headers(self.token)

            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                # DARE returns {results: [...]} format
                return data.get('results', data)
            else:
                error_msg = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_msg,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            raise DareApiError(f"Failed to connect to DARE backend: {str(e)}")


# Create global instance - can be used with or without token
conversations_client = DareConversationsClient()


def get_conversations_client(token: str = None) -> DareConversationsClient:
    """
    Get conversations client with optional token
    
    Args:
        token: JWT token for authenticated requests
        
    Returns:
        DareConversationsClient instance
    """
    return DareConversationsClient(token=token)