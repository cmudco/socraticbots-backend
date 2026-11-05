"""
DARE Files API client.

Handles file upload, management, and retrieval operations against DARE backend.
Includes internal service-to-service upload for webhook-triggered operations.
"""
import io
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


class DareFilesClient(BaseDareApiClient):
    """
    Client for DARE files management APIs
    """
    
    def upload_files(self, files: List, user_token: str, names: List[str] = None, tags: List[str] = None, folder_id: int = None, *, chunk_size: int = None, overlap_size: int = None) -> Dict[str, Any]:
        """
        Upload files to DARE backend
        
        Args:
            files: List of file objects to upload
            user_token: JWT token for authentication
            names: Optional custom names for the files
            tags: Optional list of tag names or IDs
            folder_id: Optional folder ID to organize files
            
        Returns:
            Dictionary with uploaded file information
            
        Raises:
            DareApiError: If upload fails
        """
        url = f"{self.base_url}/api/files/"
        headers = {
            'Authorization': f'Bearer {user_token}',
            'Origin': self.socratic_backend_url,
            'Referer': self.socratic_backend_url,
        }
        
        # Prepare multipart form data manually to match DARE FE format
        # Need to use files parameter for all form fields to get multiple values for 'names'
        files_data = []
        
        for i, file_obj in enumerate(files):
            # Add file
            files_data.append(('files', (file_obj.name, file_obj, file_obj.content_type or 'application/octet-stream')))
            
            # Add corresponding name
            file_name_to_use = names[i] if names and i < len(names) else file_obj.name
            files_data.append(('names', (None, file_name_to_use)))
            logger.debug(f"File {i}: using name '{file_name_to_use}' (original: '{file_obj.name}')")
        
        # Add other form fields
        data = {}
        if tags:
            data['tags'] = json.dumps(tags) if isinstance(tags, list) else tags
        if folder_id:
            data['folder_id'] = folder_id
        if chunk_size is not None:
            data['chunk_size'] = chunk_size
        if overlap_size is not None:
            data['overlap_size'] = overlap_size
        
        logger.info(f"Uploading {len(files)} files to DARE backend")
        
        try:
            response = requests.post(
                url, 
                data=data, 
                files=files_data, 
                headers=headers,
                timeout=60  # Increased timeout for file uploads
            )
            
            logger.info(f"File upload response status: {response.status_code}")
            logger.debug(f"File upload response content: {response.text}")
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"DARE file upload failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error uploading files to DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to upload files: {str(e)}"
            )

    def get_file_statuses(self, file_ids: List[int], user_token: str) -> List[Dict[str, Any]]:
        """
        Get processing status for multiple files
        
        Args:
            file_ids: List of file IDs to check
            user_token: JWT token for authentication
            
        Returns:
            List of file status dictionaries
        """
        url = f"{self.base_url}/api/files/job-statuses/"
        headers = self._get_headers(user_token)
        
        data = {'fileIds': file_ids}
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get file statuses: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"Error getting file statuses from DARE backend: {str(e)}")
            return []

    def get_user_files(self, user_token: str, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Get all files for a user
        
        Args:
            user_token: JWT token for authentication
            filters: Optional filters for files
            
        Returns:
            List of user files
        """
        url = f"{self.base_url}/api/files/"
        headers = self._get_headers(user_token)
        
        params = filters or {}
        
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get user files: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"Error getting user files from DARE backend: {str(e)}")
            return []

    def get_file_by_id(self, file_id: int, user_token: str) -> Dict[str, Any]:
        """
        Get a specific file by ID
        
        Args:
            file_id: ID of the file to retrieve
            user_token: JWT token for authentication
            
        Returns:
            File information dictionary
            
        Raises:
            DareApiError: If file not found or access denied
        """
        url = f"{self.base_url}/api/files/{file_id}/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise DareApiError(
                    message="File not found",
                    status_code=404
                )
            else:
                error_message = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error getting file from DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to retrieve file: {str(e)}"
            )

    def delete_files(self, file_ids: List[int], user_token: str) -> Dict[str, Any]:
        """
        Delete multiple files
        
        Args:
            file_ids: List of file IDs to delete
            user_token: JWT token for authentication
            
        Returns:
            Dictionary with deletion results
        """
        url = f"{self.base_url}/api/files/bulk-delete/"
        headers = self._get_headers(user_token)
        
        data = {'fileIds': file_ids}
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error deleting files from DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to delete files: {str(e)}"
            )

    def get_file_content(self, file_id: int, user_token: str) -> requests.Response:
        """
        Get file content for viewing/serving
        
        Args:
            file_id: ID of the file to retrieve
            user_token: JWT token for authentication
            
        Returns:
            HTTP response with file content
            
        Raises:
            DareApiError: If file access fails
        """
        url = f"{self.base_url}/api/files/{file_id}/view/"
        headers = {
            'Authorization': f'Bearer {user_token}',
            'Origin': self.socratic_backend_url,
            'Referer': self.socratic_backend_url,
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            
            if response.status_code not in [200, 201]:
                logger.error(f"Failed to get file content: {response.status_code}")
                raise DareApiError(
                    message="Failed to access file content",
                    status_code=response.status_code
                )
                
            return response
                
        except requests.RequestException as e:
            logger.error(f"Error getting file content from DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to retrieve file content: {str(e)}"
            )

    def create_folder(self, name: str, user_token: str) -> Dict[str, Any]:
        """
        Create a folder in DARE backend
        
        Args:
            name: Folder name
            user_token: JWT token for authentication
            
        Returns:
            Dictionary with created folder information
            
        Raises:
            DareApiError: If folder creation fails
        """
        url = f"{self.base_url}/files/api/folders/"
        headers = self._get_headers(user_token)
        
        data = {'name': name}
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
            if response.status_code in [200, 201]:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )
                
        except requests.RequestException as e:
            logger.error(f"Error creating folder in DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to create folder: {str(e)}"
            )

    def get_folders(self, user_token: str) -> List[Dict[str, Any]]:
        """
        Get all folders for a user
        
        Args:
            user_token: JWT token for authentication
            
        Returns:
            List of user folders
        """
        url = f"{self.base_url}/files/api/folders/"
        headers = self._get_headers(user_token)
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get folders: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            logger.error(f"Error getting folders from DARE backend: {str(e)}")
            return []

    def move_files_to_folder(self, file_ids: List[int], folder_id: int, user_token: str) -> Dict[str, Any]:
        """
        Move files to a folder

        Args:
            file_ids: List of file IDs to move
            folder_id: ID of the destination folder (None to remove from all folders)
            user_token: JWT token for authentication

        Returns:
            Dictionary with operation results
        """
        url = f"{self.base_url}/api/files/move/"
        headers = self._get_headers(user_token)

        data = {
            'fileIds': file_ids,
            'folderId': folder_id
        }

        try:
            response = requests.post(url, json=data, headers=headers, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            logger.error(f"Error moving files in DARE backend: {str(e)}")
            raise DareApiError(
                message=f"Failed to move files: {str(e)}"
            )

    # ========================================================================
    # Internal Service API - No user token required
    # ========================================================================

    def upload_file_internal(
        self,
        user_id: int,
        file_content: bytes,
        filename: str,
        content_type: str = 'application/pdf',
        tag_labels: List[str] = None
    ) -> Dict[str, Any]:
        """
        Upload file to DARE on behalf of a user using internal service auth.

        Used for server-to-server operations where no user JWT is available,
        such as webhook-triggered transcript uploads.

        Args:
            user_id: DARE user ID (external_user_id from VoiceAgent.user)
            file_content: File content as bytes
            filename: Filename for the uploaded file
            content_type: MIME type of the file
            tag_labels: Optional list of tag label strings (e.g. ["Exam Transcript"])

        Returns:
            Dictionary with uploaded file information

        Raises:
            DareApiError: If upload fails
        """
        internal_key = getattr(settings, 'DARE_INTERNAL_KEY', '')
        if not internal_key:
            raise DareApiError(
                message="DARE_INTERNAL_KEY not configured",
                status_code=500
            )

        url = f"{self.base_url}/api/internal/upload/"
        headers = {
            'X-Internal-Key': internal_key,
        }

        files_data = [
            ('files', (filename, io.BytesIO(file_content), content_type)),
        ]
        data = {
            'user_id': user_id,
            'names': filename,
        }
        if tag_labels:
            data['tag_labels'] = json.dumps(tag_labels)

        logger.info(f"Internal file upload: {filename} for user {user_id}")

        try:
            response = requests.post(
                url,
                data=data,
                files=files_data,
                headers=headers,
                timeout=60
            )

            if response.status_code in [200, 201]:
                logger.info(f"Internal file upload successful for user {user_id}")
                return response.json()
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"Internal file upload failed: {error_message}")
                raise DareApiError(
                    message=error_message,
                    status_code=response.status_code
                )

        except requests.RequestException as e:
            logger.error(f"Internal file upload error: {str(e)}")
            raise DareApiError(
                message=f"Failed to upload file internally: {str(e)}"
            )
