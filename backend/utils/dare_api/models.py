"""
DARE Models API client for fetching LLM models from DARE backend.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

from .base import BaseDareApiClient, DareApiError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotModelCheckResult:
    """DARE's problem code per bot model field, or ``None`` when that model is fine."""

    chat_model_problem: Optional[str]
    tracking_model_problem: Optional[str]


class DareModelsClient(BaseDareApiClient):
    """
    Client for DARE Models API
    Handles fetching available LLM models from DARE backend
    """
    
    def get_llm_models(self, user_token: str = None) -> List[Dict[str, Any]]:
        """
        Fetch available LLM models from DARE backend
        
        Args:
            user_token: Optional JWT token for authenticated requests
            
        Returns:
            List of LLM model dictionaries
            
        Raises:
            DareApiError: If the request fails
        """
        url = f"{self.base_url}/api/llms/all_models/"
        headers = self._get_headers(user_token)
        
        try:
            logger.info(f"Fetching LLM models from DARE: {url}")
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                models = response.json()
                logger.info(f"Successfully fetched {len(models)} LLM models from DARE")
                return models
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"Failed to fetch LLM models from DARE: {error_message}")
                raise DareApiError(
                    f"Failed to fetch LLM models: {error_message}", 
                    response.status_code,
                    response.json() if response.content else None
                )
                
        except requests.RequestException as e:
            logger.error(f"Network error while fetching LLM models from DARE: {str(e)}")
            raise DareApiError(f"Network error: {str(e)}")

    def get_wallet_scoped_models(
        self, wallet_scope: str, user_token: str = None
    ) -> Dict[str, Any]:
        """
        Fetch wallet-aware models from DARE.

        Returns the ``{models, wallet}`` envelope filtered to whatever wallet
        will pay (``wallet_scope=active`` or ``wallet_scope=bot:<id>``).
        Pass-through to the FE — DARE returns camelCase so SB does not
        re-camelize.
        """
        url = f"{self.base_url}/api/llms/"
        params = {"wallet_scope": wallet_scope}
        headers = self._get_headers(user_token)

        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return response.json()
            error_message = self._parse_dare_error(response)
            raise DareApiError(
                f"Failed to fetch wallet-scoped models: {error_message}",
                response.status_code,
                response.json() if response.content else None,
            )
        except requests.RequestException as e:
            logger.error(
                f"Network error while fetching wallet-scoped models from DARE: {str(e)}"
            )
            raise DareApiError(f"Network error: {str(e)}")

    def check_bot_models(
        self,
        owner_dare_user_id: int,
        chat_model_dare_id: Optional[str],
        tracking_model_dare_id: Optional[str],
    ) -> BotModelCheckResult:
        """Ask DARE whether a bot's owner may save these models on it."""
        url = f"{self.base_url}/api/internal/bot-model-check/"
        headers = {
            **self._get_headers(),
            'X-Internal-Key': getattr(settings, 'DARE_INTERNAL_KEY', ''),
        }
        payload = {
            'owner_dare_user_id': owner_dare_user_id,
            'chat_model_dare_id': chat_model_dare_id,
            'tracking_model_dare_id': tracking_model_dare_id,
        }
        try:
            # DARE may probe the LiteLLM gateway (up to 10s) before answering.
            response = requests.post(url, headers=headers, json=payload, timeout=20)
        except requests.RequestException as e:
            logger.error("Network error checking bot models with DARE: %s", e)
            raise DareApiError(f"Network error: {str(e)}")
        if response.status_code != 200:
            raise DareApiError(
                f"DARE bot model check failed: {self._parse_dare_error(response)}",
                response.status_code,
            )
        body = response.json()
        return BotModelCheckResult(
            chat_model_problem=body.get('chatModelProblem'),
            tracking_model_problem=body.get('trackingModelProblem'),
        )

    def get_llm_model(self, model_id: int, user_token: str = None) -> Dict[str, Any]:
        """
        Fetch a specific LLM model from DARE backend
        
        Args:
            model_id: ID of the LLM model
            user_token: Optional JWT token for authenticated requests
            
        Returns:
            LLM model dictionary
            
        Raises:
            DareApiError: If the request fails
        """
        url = f"{self.base_url}/api/llms/all_models/{model_id}/"
        headers = self._get_headers(user_token)
        
        try:
            logger.info(f"Fetching LLM model {model_id} from DARE: {url}")
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                model = response.json()
                logger.info(f"Successfully fetched LLM model {model_id} from DARE")
                return model
            else:
                error_message = self._parse_dare_error(response)
                logger.error(f"Failed to fetch LLM model {model_id} from DARE: {error_message}")
                raise DareApiError(
                    f"Failed to fetch LLM model: {error_message}", 
                    response.status_code,
                    response.json() if response.content else None
                )
                
        except requests.RequestException as e:
            logger.error(f"Network error while fetching LLM model {model_id} from DARE: {str(e)}")
            raise DareApiError(f"Network error: {str(e)}")