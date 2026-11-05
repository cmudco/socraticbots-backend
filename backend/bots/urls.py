# bots/urls.py
from django.urls import path, include
from rest_framework_nested import routers
from .views import (
    BotGroupViewSet,
    BotViewSet,
    get_bot_billing_config,
    get_bots_using_litellm_key,
    get_bots_using_model,
    get_dare_llms,
    nullify_litellm_key_references,
    nullify_model_references,
    update_bot_budget,
    update_bot_cap,
)

# Main router for bot groups
router = routers.DefaultRouter()
router.register(r'bot-groups', BotGroupViewSet, basename='botgroup')

# Nested router for bots within bot groups
bot_groups_router = routers.NestedDefaultRouter(router, r'bot-groups', lookup='bot_group')
bot_groups_router.register(r'bots', BotViewSet, basename='botgroup-bots')

urlpatterns = [
    path('api/', include(router.urls)),
    path('api/', include(bot_groups_router.urls)),
    path('api/bots/dare-llms/', get_dare_llms, name='dare-llms-list'),
    path('api/bots/dare-llms/<int:model_id>/', get_dare_llms, name='dare-llms-detail'),

    # Internal endpoints (called by DARE backend, X-Internal-Key required)
    path('api/bots/internal/update-budget/', update_bot_budget, name='update-bot-budget'),
    path(
        'api/bots/internal/model-dependents/<int:model_id>/',
        get_bots_using_model,
        name='model-dependents',
    ),
    path(
        'api/bots/internal/nullify-model/<int:model_id>/',
        nullify_model_references,
        name='nullify-model',
    ),
    path(
        'api/bots/internal/litellm-key-dependents/<uuid:key_id>/',
        get_bots_using_litellm_key,
        name='litellm-key-dependents',
    ),
    path(
        'api/bots/internal/nullify-litellm-key/<uuid:key_id>/',
        nullify_litellm_key_references,
        name='nullify-litellm-key',
    ),
    path(
        'api/bots/internal/<int:bot_id>/billing-config/',
        get_bot_billing_config,
        name='get-bot-billing-config',
    ),
    path(
        'api/bots/internal/<int:bot_id>/update-cap/',
        update_bot_cap,
        name='update-bot-cap',
    ),
]
