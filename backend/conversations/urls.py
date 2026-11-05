from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views, public_views

app_name = 'conversations'

# Router for public bot ViewSet
router = DefaultRouter()
router.register(r'public/bots', public_views.PublicBotViewSet, basename='public-bot')

urlpatterns = [
    # Bot conversation management (authenticated)
    path('bots/<int:bot_id>/conversations/', views.get_or_create_bot_conversation, name='get_or_create_bot_conversation'),

    # Professor view of user conversations (Bot Access Management)
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/users/<int:user_id>/conversations/', views.get_user_bot_conversations, name='get_user_bot_conversations'),

    # Professor view of anonymous conversations for public bots
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/anonymous-conversations/', views.get_anonymous_bot_conversations, name='get_anonymous_bot_conversations'),

    # Professor read-only view of conversation messages
    path('bot-groups/<int:bot_group_id>/bots/<int:bot_id>/conversations/<str:conversation_id>/messages/', views.get_conversation_messages_readonly, name='get_conversation_messages_readonly'),

    # Public bot endpoints (ViewSet routes)
    path('', include(router.urls)),

    # DARE backend proxy endpoints
    path('<str:conversation_id>/messages/', views.get_conversation_messages, name='get_conversation_messages'),
    path('<str:conversation_id>/delete/', views.delete_conversation, name='delete_conversation'),
    path('messages/<str:message_id>/delete/', views.delete_message, name='delete_message'),
    path('<str:conversation_id>/export-pdf/', views.export_conversation_pdf, name='export_conversation_pdf'),
    path('models/', views.get_available_models, name='get_available_models'),
]