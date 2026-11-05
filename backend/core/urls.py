#backend/core/urls.py
"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core.views import health_check, readiness_check


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health-check'),
    path('api/ready/', readiness_check, name='readiness-check'),
    path('api/users/', include('users.urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('api/files/', include('files.urls')),
    path('api/access-codes/', include('access_codes.urls')),
    path('api/conversations/', include('conversations.urls')),  # DARE conversation proxy
    path('api/', include('notes.urls')),
    path('', include('bots.urls')),  # New bot ecosystem URLs
    path('api/voice/', include('voice.urls', namespace='voice')),  # ElevenLabs voice agents
    path('api/wallet/', include('wallet.urls')),  # Pass-through proxy to DARE billing
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)