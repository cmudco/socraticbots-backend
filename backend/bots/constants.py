"""
Bots app constants.

``BillingSourceChoice`` is consumed by the wallet router on the DARE side via
the internal ``/api/bots/internal/{bot_id}/billing-config/`` endpoint to decide
whose wallet pays for a bot LLM call. The string values are the contract
between the two services — do not rename without updating the DARE wallet
router as well.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _


class BillingSourceChoice(models.TextChoices):
    """Where the money for a bot's LLM call comes from."""

    OWNER_WALLET = "OWNER_WALLET", _("Owner's DARE Wallet")
    GROUP_WALLET = "GROUP_WALLET", _("Access-Code Group Wallet")
    USER_WALLET = "USER_WALLET", _("Calling User's Wallet")
    LITELLM_KEY = "LITELLM_KEY", _("LiteLLM Proxy Key")


MODEL_PREFERENCE_FIELDS = ('chat_model_dare_id', 'tracking_model_dare_id')

# DARE's bot-model check codes, as the owner reads them on the bot form.
MODEL_PROBLEM_MESSAGES = {
    'MODEL_NOT_AVAILABLE': _("This model isn't available to you. Pick another model."),
    'KEY_UNAVAILABLE': _(
        "You can no longer use the LiteLLM key behind this model. Pick another model."
    ),
    'MODEL_NOT_ON_KEY': _(
        "Your LiteLLM gateway doesn't list this model right now. Pick another model."
    ),
    'TRACKING_NEEDS_DARE_MODEL': _(
        "Progress tracking needs a DARE model, not one from a LiteLLM key."
    ),
}
MODEL_CHECK_UNAVAILABLE = _("Couldn't confirm this model with DARE. Try saving again.")
