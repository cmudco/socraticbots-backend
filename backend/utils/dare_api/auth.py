"""
DARE Authentication API client
"""

import requests
from typing import Dict, Any
import logging

from django.conf import settings

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


class DareAuthClient(BaseDareApiClient):
    """
    Client for DARE authentication and user management APIs
    """
    
    def authenticate_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        Authenticate user with DARE backend and return JWT tokens
        
        Args:
            email: User's email address
            password: User's password
            
        Returns:
            Authentication response with JWT tokens
            
        Raises:
            DareApiError: If authentication fails
        """
        url = f"{self.base_url}/users/api/dj-rest-auth/login/"
        headers = self._get_headers()
        
        login_data = {
            'email': email,
            'password': password
        }
        
        logger.info(f"Attempting DARE authentication for: {email}")
        logger.info(f"DARE backend URL: {url}")
        
        try:
            response = requests.post(url, json=login_data, headers=headers, timeout=10)
            
            logger.info(f"Response status code: {response.status_code}")
            # Login responses contain access and refresh tokens. Never emit the
            # response body to logs; the status code is sufficient for tracing.
            
            if response.status_code == 200:
                if response.content:
                    try:
                        login_response = response.json()
                        # Add SocraticBots-specific fields
                        login_response['platform'] = 'SocraticBots'
                        logger.info(f"Successful DARE authentication for: {email}")
                        return login_response
                    except ValueError as e:
                        logger.error(f"Failed to parse JSON response: {e}")
                        raise DareApiError(
                            message=f"Invalid response format from authentication service",
                            status_code=response.status_code
                        )
                else:
                    logger.error("Empty response from DARE backend")
                    raise DareApiError(
                        message="Empty response from authentication service",
                        status_code=response.status_code
                    )
            else:
                # Login failed, parse error response
                error_data = response.json() if response.content else {'error': 'Authentication failed'}
                error_message = self._parse_dare_error(response) if response.content else 'Authentication failed'
                logger.warning(f"Failed DARE authentication for: {email}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code,
                    details=error_data
                )
                
        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Unable to connect to authentication service: {str(e)}"
            )
    
    def request_password_reset(self, email: str) -> Dict[str, Any]:
        """
        Request a password reset via DARE backend.

        The Origin/Referer headers (set by _get_headers) tell DARE's
        AccountAdapter to include the Socratic Bots frontend URL as the
        callbackurl in the password-reset email link.

        Args:
            email: User's email address

        Returns:
            Success response data from DARE

        Raises:
            DareApiError: If the request fails
        """
        url = f"{self.base_url}/users/api/dj-rest-auth/password/reset/"
        headers = self._get_headers()

        try:
            response = requests.post(
                url, json={'email': email}, headers=headers, timeout=10
            )

            if response.status_code == 200:
                return response.json() if response.content else {'detail': 'Password reset email sent.'}
            else:
                error_message = self._parse_dare_error(response) if response.content else 'Password reset request failed'
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE backend for password reset: {str(e)}")
            raise DareApiError(
                message=f"Unable to connect to authentication service: {str(e)}"
            )

    def register_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a user in DARE backend

        Args:
            user_data: User registration data

        Returns:
            Success response data

        Raises:
            DareApiError: If registration fails
        """
        url = f"{self.base_url}/users/api/dj-rest-auth/registration/"
        headers = self._get_headers()
        
        try:
            response = requests.post(url, json=user_data, headers=headers)
            
            if response.status_code == 201:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code,
                    details=user_data
                )
                
        except requests.RequestException as e:
            raise DareApiError(
                message=f"Failed to connect to DARE backend: {str(e)}",
                details=user_data
            )
    
    def validate_user_token(self, token: str) -> bool:
        """
        Validate a user token with DARE backend
        
        Args:
            token: JWT token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        url = f"{self.base_url}/users/token/verify/"
        headers = self._get_headers()
        
        try:
            response = requests.post(url, json={'token': token}, headers=headers)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def get_user_info(self, user_token: str) -> Dict[str, Any]:
        """
        Get user info from DARE backend using the user's JWT token.
        This fetches the current user's profile including platform_role.

        Args:
            user_token: The user's JWT access token

        Returns:
            User info dictionary with platformRole and other fields

        Raises:
            DareApiError: If the request fails
        """
        url = f"{self.base_url}/users/api/dj-rest-auth/user/"
        headers = self._get_headers()
        headers['Authorization'] = f'Bearer {user_token}'

        logger.info(f"Fetching user info from DARE")

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                user_info = response.json()
                logger.info(f"Successfully fetched DARE user info")
                return user_info
            else:
                error_message = self._parse_dare_error(response) if response.content else 'Failed to fetch user info'
                logger.warning(f"Failed to fetch DARE user info: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE backend for user info: {str(e)}")
            raise DareApiError(
                message=f"Unable to connect to DARE backend: {str(e)}"
            )

    def check_access_code_exists(self, access_code: str) -> Dict[str, Any]:
        """
        Check if an access code exists in DARE backend and get its role information.

        Args:
            access_code: The access code to check

        Returns:
            Dictionary with exists (bool), defaultRole (str), availableSlots (int), and message (str).
            Note: DARE uses djangorestframework-camelcase so keys are camelCase.

        Raises:
            DareApiError: If there's an error communicating with DARE backend
        """
        url = f"{self.base_url}/users/api/access-codes/check/"
        headers = self._get_headers()
        
        check_data = {
            'access_code': access_code
        }
        
        logger.info(f"Checking DARE access code: {access_code}")
        logger.info(f"DARE backend URL: {url}")
        
        try:
            response = requests.post(url, json=check_data, headers=headers, timeout=10)
            
            logger.info(f"Access code check response status: {response.status_code}")
            logger.info(f"Access code check response: {response.text}")
            
            if response.status_code == 200:
                try:
                    check_response = response.json()
                    logger.info(f"DARE access code check successful for: {access_code}")
                    return check_response
                except ValueError as e:
                    logger.error(f"Failed to parse access code check response: {e}")
                    raise DareApiError(
                        message="Invalid response format from access code check service",
                        status_code=response.status_code
                    )
            else:
                # Access code doesn't exist or error occurred
                logger.warning(f"DARE access code check failed for: {access_code}")
                return {
                    'exists': False,
                    'defaultRole': None,
                    'availableSlots': 0,
                    'message': 'Access code not found in DARE backend'
                }
                
        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE backend for access code check: {str(e)}")
            # Return False for exists so registration can continue with SocraticBots-only access
            return {
                'exists': False,
                'defaultRole': None,
                'availableSlots': 0,
                'message': f"Unable to connect to DARE backend: {str(e)}"
            }

    def provision_voice_access_code(
        self,
        access_code: str,
        action: str = "ensure",
        activate: bool = False,
    ) -> Dict[str, Any]:
        """
        Register a Socratic Bots voice-assignment code in DARE as a RESEARCHER
        registration code (service-to-service, X-Internal-Key).

        Returns DARE's response dict. A code owned by a different registration
        group comes back as ``{'conflict': True, ...}`` rather than an exception
        so callers can turn it into a user-facing validation error.

        Raises:
            DareApiError: when DARE is unreachable, the key is not configured,
            or DARE answers with an unexpected status.
        """
        internal_key = getattr(settings, 'DARE_INTERNAL_KEY', '')
        if not internal_key:
            raise DareApiError(message="DARE_INTERNAL_KEY is not configured")

        url = f"{self.base_url}/users/api/internal/voice-access-codes/"
        headers = self._get_headers()
        headers['X-Internal-Key'] = internal_key
        payload = {'access_code': access_code, 'action': action}
        if action == 'ensure':
            payload['activate'] = activate

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE for voice access code provisioning: {e}")
            raise DareApiError(message=f"Unable to connect to DARE backend: {e}")

        if response.status_code == 200:
            return response.json()
        if response.status_code == 409:
            body = response.json() if response.content else {}
            return {'conflict': True, 'message': body.get('message', 'Access code is already in use')}

        logger.error(
            f"DARE voice access code provisioning failed: status={response.status_code}"
        )
        raise DareApiError(
            message=self._parse_dare_error(response) if response.content else 'Provisioning failed',
            status_code=response.status_code,
        )

    def sync_access_code_to_dare(
        self,
        user_token: str,
        access_code: str,
        max_capacity: int = 9999,
        default_role: str = "SB_USER",
        action: str = "sync",
    ) -> Dict[str, Any]:
        """
        Sync a subscription code from Socratic Bots to DARE as an AccessCodeGroup.

        Args:
            user_token: The user's JWT access token for DARE authentication
            access_code: The code string to sync
            max_capacity: Maximum number of redemptions (0/unlimited maps to 9999)
            default_role: Role assigned to users who register with this code
            action: "sync" to create/update, "delete" to deactivate

        Returns:
            Response dict with success status and details
        """
        try:
            url = f"{self.base_url}/users/api/internal/sync-access-code/"
            headers = self._get_headers(user_token)

            # Map 0 (unlimited) to a large number for DARE
            if max_capacity <= 0:
                max_capacity = 9999

            payload = {
                'access_code': access_code,
                'max_capacity': max_capacity,
                'default_role': default_role,
                'action': action,
            }

            logger.info(f"Syncing access code to DARE: code={access_code}, action={action}")
            response = requests.post(url, json=payload, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                logger.info(f"DARE access code sync successful: {data}")
                return data
            else:
                logger.error(
                    f"DARE access code sync failed: status={response.status_code}, "
                    f"body={response.text}"
                )
                return {
                    'success': False,
                    'message': f"DARE sync failed with status {response.status_code}"
                }

        except requests.RequestException as e:
            logger.error(f"Error connecting to DARE for access code sync: {str(e)}")
            return {
                'success': False,
                'message': f"Unable to connect to DARE backend: {str(e)}"
            }
