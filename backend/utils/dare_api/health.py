"""
DARE health probe, used by this backend's readiness check.
"""

import requests

from .base import BaseDareApiClient, DareApiError


class DareHealthClient(BaseDareApiClient):
    """Checks that the DARE backend is reachable."""

    def check_health(self) -> None:
        """
        Raises:
            DareApiError: DARE did not answer `/api/health/` with a 2xx within 3 seconds.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/health/", headers=self._get_headers(), timeout=3,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise DareApiError(f"DARE health check failed: {error.__class__.__name__}") from error
