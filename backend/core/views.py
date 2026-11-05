"""
Liveness and readiness endpoints for container health checks and load balancers.
"""

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from utils.dare_api import DareApiError, health_client

SERVICE_NAME = "socraticbots-backend"


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """Liveness: the process answers. Touches neither the database nor DARE."""
    return JsonResponse({
        "status": "ok",
        "service": SERVICE_NAME,
        "timestamp": timezone.now().isoformat(),
    })


@require_GET
def readiness_check(request: HttpRequest) -> JsonResponse:
    """Readiness: the database and DARE are reachable. Answers 503 when either is down."""
    checks = {}

    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception as error:
        checks["database"] = f"error: {error.__class__.__name__}"

    try:
        health_client.check_health()
        checks["dare"] = "ok"
    except DareApiError as error:
        checks["dare"] = f"error: {error.message}"

    is_ready = all(value == "ok" for value in checks.values())
    return JsonResponse(
        {
            "status": "ready" if is_ready else "not_ready",
            "service": SERVICE_NAME,
            "checks": checks,
            "timestamp": timezone.now().isoformat(),
        },
        status=200 if is_ready else 503,
    )
