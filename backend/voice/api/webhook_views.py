"""
ElevenLabs Webhook Views.

Receives webhook events from ElevenLabs Conversational AI platform.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from voice.dtos import ElevenLabsWebhookPayload
from voice.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def elevenlabs_webhook(request) -> JsonResponse:
    """
    Receive webhook from ElevenLabs after conversation ends.

    Flow:
    1. Verify HMAC signature
    2. Parse payload into typed DTO
    3. Delegate to WebhookService for processing
    4. Return 200 OK to acknowledge receipt

    Headers:
        ElevenLabs-Signature: HMAC-SHA256 signature

    Body:
        JSON with type, data (containing conversation_id, agent_id, transcript), event_timestamp
    """
    service = WebhookService()

    # Verify signature - ElevenLabs uses "ElevenLabs-Signature" header
    signature = request.headers.get('ElevenLabs-Signature', '')
    if not service.verify_signature(request.body, signature):
        logger.info("Invalid webhook signature")
        return JsonResponse({"error": "Invalid signature"}, status=401)

    try:
        # Parse into typed DTO
        data = json.loads(request.body)
        payload = ElevenLabsWebhookPayload.from_dict(data)

        # Process webhook (save transcript, cleanup ElevenLabs)
        service.process_conversation_end(payload)

        return JsonResponse({"status": "ok"})

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook: {e}")
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return JsonResponse({"error": str(e)}, status=500)
