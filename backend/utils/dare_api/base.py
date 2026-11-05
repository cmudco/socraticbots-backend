"""
Base DARE API client with common functionality and error handling.
"""

import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class DareApiError(Exception):
    """Custom exception for DARE API errors"""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class BaseDareApiClient:
    """
    Base client for DARE API communication with shared functionality
    """
    
    def __init__(self):
        self.base_url = getattr(settings, 'DARE_BACKEND_URL')
        self.socratic_backend_url = getattr(settings, 'SOCRATIC_BOTS_BACKEND_URL')
    
    def _get_headers(self, user_token: str = None) -> Dict[str, str]:
        """Get standard headers for DARE API requests"""
        headers = {
            'Content-Type': 'application/json',
            'Origin': self.socratic_backend_url,
            'Referer': self.socratic_backend_url,
        }
        
        if user_token:
            headers['Authorization'] = f'Bearer {user_token}'
            
        return headers
    
    def _parse_dare_error(self, response: requests.Response) -> str:
        """
        Parse DARE backend error response into user-friendly message
        
        Args:
            response: Failed HTTP response from DARE
            
        Returns:
            Clean error message for frontend consumption
        """
        try:
            dare_error = response.json()
            
            if isinstance(dare_error, dict):
                # Handle field-specific errors (like password validation)
                error_messages = []
                
                for field, errors in dare_error.items():
                    # Clean field names for better UX
                    clean_field = self._clean_field_name(field)
                    
                    if isinstance(errors, list):
                        for error in errors:
                            error_messages.append(f"{clean_field}: {error}")
                    else:
                        error_messages.append(f"{clean_field}: {errors}")
                
                if error_messages:
                    # Return single message for single error, joined for multiple
                    if len(error_messages) == 1:
                        return error_messages[0]
                    else:
                        return '; '.join(error_messages)
                else:
                    return "Request failed due to validation errors"
            else:
                return str(dare_error)
                
        except (ValueError, TypeError):
            # If response is not JSON, return the raw text
            return f"DARE API failed: {response.text}"
    
    def _clean_field_name(self, field: str) -> str:
        """Convert API field names to user-friendly names"""
        field_mapping = {
            'password1': 'Password',
            'password2': 'Confirm Password',
            'email': 'Email',
            'name': 'Name',
            'access_code': 'Access Code',
            'non_field_errors': 'Validation Error'
        }
        return field_mapping.get(field, field.replace('_', ' ').title())


def handle_dare_api_error(func):
    """
    Decorator to handle DARE API errors and convert them to DRF ValidationErrors
    
    Usage:
        @handle_dare_api_error
        def my_api_method(self):
            return dare_api.register_user(data)
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DareApiError as e:
            raise ValidationError(e.message)
    return wrapper