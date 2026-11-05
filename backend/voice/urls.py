# voice/urls.py
"""
URL configuration for Voice app.
"""

from django.urls import path, include

app_name = 'voice'

urlpatterns = [
    path('', include('voice.api.urls')),
]
