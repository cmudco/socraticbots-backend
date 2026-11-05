"""
``/api/wallet/*`` routes — thin pass-through to DARE billing endpoints.
"""
from django.urls import path

from .views import (
    bot_usage,
    litellm_key_create,
    litellm_key_dependents,
    litellm_key_detail,
    litellm_key_test_saved,
    litellm_key_test_unsaved,
    provider_key_delete,
    provider_key_save,
    provider_key_status,
    wallet_effective_policy,
    wallet_list,
    wallet_set_active,
    wallet_transactions,
)

urlpatterns = [
    path('', wallet_list, name='wallet-list'),
    path('active/', wallet_set_active, name='wallet-set-active'),
    path('transactions/', wallet_transactions, name='wallet-transactions'),
    path('effective-policy/', wallet_effective_policy, name='wallet-effective-policy'),
    path('litellm/', litellm_key_create, name='wallet-litellm-create'),
    path('litellm/test/', litellm_key_test_unsaved, name='wallet-litellm-test'),
    path('litellm/<uuid:key_id>/', litellm_key_detail, name='wallet-litellm-detail'),
    path(
        'litellm/<uuid:key_id>/test/',
        litellm_key_test_saved,
        name='wallet-litellm-test-saved',
    ),
    path(
        'litellm/<uuid:key_id>/dependents/',
        litellm_key_dependents,
        name='wallet-litellm-dependents',
    ),
    path('provider-keys/status/', provider_key_status, name='wallet-provider-status'),
    path('provider-keys/', provider_key_save, name='wallet-provider-save'),
    path(
        'provider-keys/<str:provider>/',
        provider_key_delete,
        name='wallet-provider-delete',
    ),
    path('bots/<int:bot_id>/usage/', bot_usage, name='wallet-bot-usage'),
]
