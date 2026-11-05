# backend/files/urls.py
from django.urls import path
from .views import BotFileViewSet, SecureFileServeView

urlpatterns = [
    # Bot files endpoints
    path('bots/<int:bot_id>/', BotFileViewSet.as_view({
        'get': 'list',
        'post': 'create'
    }), name='bot-files-list'),
    path('bots/<int:bot_id>/<int:pk>/', BotFileViewSet.as_view({
        'delete': 'destroy'
    }), name='bot-files-detail'),
    path('bots/<int:bot_id>/<int:pk>/download/', BotFileViewSet.as_view({
        'get': 'download'
    }), name='bot-files-download'),
    
    # Secure file serving
    path('serve/<int:file_id>/', SecureFileServeView.as_view(), name='serve-file'),
]
