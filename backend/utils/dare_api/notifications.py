"""
DARE Notifications API client for fetching notifications via proxy.
"""

import requests
from typing import Dict, Any, List, Optional
import logging

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


class DareNotificationsClient(BaseDareApiClient):
    """
    Client for DARE notifications API.
    Fetches notifications for authenticated users.
    """
    
    def get_notifications(
        self, 
        user_token: str,
        status: Optional[str] = None,
        exclude_expired: bool = True,
        include_read: bool = False,
    ) -> Dict[str, Any]:
        """
        Get notifications for the authenticated user.
        
        Args:
            user_token: JWT token for authentication
            status: Optional filter by status (unread, read, archived)
            exclude_expired: Whether to exclude expired notifications
            include_read: Whether to include already-read notification history
            
        Returns:
            Paginated notifications response
            
        Raises:
            DareApiError: If the API request fails
        """
        url = f"{self.base_url}/api/notifications/"
        headers = self._get_headers(user_token)
        
        params = {}
        if status:
            params['status'] = status
        if exclude_expired:
            params['exclude_expired'] = 'true'
        if include_read:
            params['include_read'] = 'true'
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE notifications fetch failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error fetching notifications from DARE: {str(e)}")
            raise DareApiError(
                message=f"Failed to fetch notifications: {str(e)}"
            )
    
    def get_notification_stats(self, user_token: str) -> Dict[str, Any]:
        """
        Get notification statistics for the authenticated user.
        
        Args:
            user_token: JWT token for authentication
            
        Returns:
            Notification statistics
            
        Raises:
            DareApiError: If the API request fails
        """
        url = f"{self.base_url}/api/notifications/stats/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE notification stats fetch failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error fetching notification stats from DARE: {str(e)}")
            raise DareApiError(
                message=f"Failed to fetch notification stats: {str(e)}"
            )
    
    def mark_notification_as_read(self, notification_id: int, user_token: str) -> Dict[str, Any]:
        """
        Mark a specific notification as read.
        
        Args:
            notification_id: ID of the notification to mark
            user_token: JWT token for authentication
            
        Returns:
            Updated notification data
            
        Raises:
            DareApiError: If the API request fails
        """
        url = f"{self.base_url}/api/notifications/{notification_id}/mark-read/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE mark notification read failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error marking notification as read in DARE: {str(e)}")
            raise DareApiError(
                message=f"Failed to mark notification as read: {str(e)}"
            )
    
    def mark_all_as_read(self, user_token: str) -> Dict[str, Any]:
        """
        Mark all notifications as read for the authenticated user.
        
        Args:
            user_token: JWT token for authentication
            
        Returns:
            Response with count of updated notifications
            
        Raises:
            DareApiError: If the API request fails
        """
        url = f"{self.base_url}/api/notifications/mark-all-read/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE mark all notifications read failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error marking all notifications as read in DARE: {str(e)}")
            raise DareApiError(
                message=f"Failed to mark all notifications as read: {str(e)}"
            )
    
    def clear_all_notifications(self, user_token: str) -> Dict[str, Any]:
        """
        Clear (soft-delete) all notifications for the authenticated user.
        
        Args:
            user_token: JWT token for authentication
            
        Returns:
            Response with count of cleared notifications
            
        Raises:
            DareApiError: If the API request fails
        """
        url = f"{self.base_url}/api/notifications/clear-all/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.delete(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE clear all notifications failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error clearing notifications in DARE: {str(e)}")
            raise DareApiError(
                message=f"Failed to clear notifications: {str(e)}"
            )


# Singleton instance
notifications_client = DareNotificationsClient()
