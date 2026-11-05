#backend/users/urls.py
from django.urls import path
from .views import (
    RegisterView, UserDetailView, 
    CookieTokenObtainPairView, CookieTokenRefreshView, 
    CookieTokenVerifyView, LogoutView, authenticate_with_dare, user_info, forgot_password,
    # Notification proxy views
    get_notifications, get_notification_stats, mark_notification_read,
    mark_all_notifications_read, clear_all_notifications,
    internal_delete_user
)
from django.views.decorators.csrf import csrf_protect

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('me/', UserDetailView.as_view(), name='user-detail'),
    
    # DARE authentication endpoints
    path('login/', authenticate_with_dare, name='authenticate_with_dare'),
    path('forgot-password/', forgot_password, name='forgot_password'),
    path('user-info/', user_info, name='user_info'),
    
    # Replace standard token views with DARE forwarding
    path('token/', authenticate_with_dare, name='token_obtain_pair'),
    path('token/refresh/', csrf_protect(CookieTokenRefreshView.as_view()), name='token_refresh'),
    path('token/verify/', csrf_protect(CookieTokenVerifyView.as_view()), name='token_verify'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Internal service-to-service endpoint (DARE account expunge)
    path('internal/delete-user/', internal_delete_user, name='internal_delete_user'),
    
    # Notification proxy endpoints
    path('notifications/', get_notifications, name='get_notifications'),
    path('notifications/stats/', get_notification_stats, name='get_notification_stats'),
    path('notifications/<int:notification_id>/mark-read/', mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', mark_all_notifications_read, name='mark_all_notifications_read'),
    path('notifications/clear-all/', clear_all_notifications, name='clear_all_notifications'),
]

