# backend/users/views.py
import json
import logging
import requests

from django.conf import settings
from django.contrib.auth import get_user_model, authenticate, login
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import generics, permissions, throttling, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from utils.dare_api import auth_client, DareApiError
from utils.auth import get_bearer_token
from utils.internal_auth import require_internal_key
from .authentication import JWTAuthentication
from .serializers import UserSerializer, RegisterSerializer, UserInfoSerializer

logger = logging.getLogger('security')

User = get_user_model()

class RegisterThrottle(throttling.AnonRateThrottle):
    rate = '3/hour'

class PasswordResetThrottle(AnonRateThrottle):
    rate = '3/hour'

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer
    throttle_classes = [RegisterThrottle]
    
    def perform_create(self, serializer):
        user = serializer.save()
        logger.info(f"New user registered: {user.username} (IP: {self.request.META.get('REMOTE_ADDR')})")


class UserDetailView(generics.RetrieveUpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated,)
    http_method_names = ['get', 'patch']  # Restrict to GET and PATCH only

    def get_object(self):
        return self.request.user

    def perform_update(self, serializer):
        # Log user profile updates for audit
        logger.info(f"User {self.request.user.username} updated profile (IP: {self.request.META.get('REMOTE_ADDR')})")
        serializer.save()


# Cookie-based token views
class CookieTokenObtainPairView(TokenObtainPairView):
    throttle_scope = 'auth'  # Apply auth throttling

    def post(self, request, *args, **kwargs):
        # Log login attempt for security monitoring
        logger.info(f"Login attempt for user: {request.data.get('username')} (IP: {request.META.get('REMOTE_ADDR')})")

        response = super().post(request, *args, **kwargs)

        # Get the refresh token from the response data
        refresh_token = response.data.get('refresh')

        if refresh_token:
            # Set the refresh token in a HttpOnly cookie
            response.set_cookie(
                'refresh_token',
                refresh_token,
                max_age=7 * 24 * 60 * 60,  # 7 days
                httponly=True,
                secure=True,
                samesite='Lax',
                path='/api/users/token/refresh/'
            )

            # Log successful login
            logger.info(f"Successful login for user: {request.data.get('username')} (IP: {request.META.get('REMOTE_ADDR')})")

        # Return the original response with both token in body and cookie
        return response


class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        # Get refresh token from cookie if not in request data
        if 'refresh' not in request.data and 'refresh_token' in request.COOKIES:
            request.data['refresh'] = request.COOKIES.get('refresh_token')

        response = super().post(request, *args, **kwargs)

        # If there's a new refresh token in the response, update the cookie
        if 'refresh' in response.data:
            refresh_token = response.data.get('refresh')
            response.set_cookie(
                'refresh_token',
                refresh_token,
                max_age=7 * 24 * 60 * 60,  # 7 days
                httponly=True,
                secure=True,
                samesite='Lax',
                path='/api/users/token/refresh/'
            )

        return response


class CookieTokenVerifyView(TokenVerifyView):
    # Standard view - no changes needed
    pass


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Log logout event
        logger.info(f"User {request.user.username} logged out (IP: {request.META.get('REMOTE_ADDR')})")

        # Get the refresh token from cookie
        refresh_token = request.COOKIES.get('refresh_token')

        response = Response({"detail": "Successfully logged out."})

        # Clear the refresh token cookie
        response.delete_cookie(
            'refresh_token',
            path='/api/users/token/refresh/',
            domain=None,
            samesite='Lax'
        )

        # Blacklist the token if available
        if refresh_token:
            try:
                token = OutstandingToken.objects.get(token=refresh_token)
                BlacklistedToken.objects.create(token=token)
            except Exception as e:
                # Token might be already blacklisted or invalid
                pass

        return response

@api_view(['POST'])
@permission_classes([AllowAny])
def authenticate_with_dare(request):
    """
    Authenticate user with DARE backend and return JWT tokens.
    This endpoint uses the centralized DareApiClient for authentication.
    Also syncs the DARE user ID to SocraticBots user's external_user_id.
    If the user does not exist in SocraticBots, create it using DARE info.
    """
    try:
        email = request.data.get('email') if hasattr(request.data, 'get') else None
        password = request.data.get('password') if hasattr(request.data, 'get') else None

        if not email or not password:
            return Response(
                {'error': 'Email and password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use centralized DARE API client
        try:
            login_response = auth_client.authenticate_user(email, password)

            # Extract DARE user ID and info from the response
            dare_user = login_response.get('user') if isinstance(login_response.get('user'), dict) else {}
            dare_user_id = dare_user.get('id')
            dare_user_email = dare_user.get('email')
            dare_user_name = dare_user.get('name') or (dare_user_email.split('@')[0] if dare_user_email else 'DARE User')

            if dare_user_id and dare_user_email:
                # Find and update SocraticBots user with external_user_id
                try:
                    sb_user = User.objects.get(email=dare_user_email)
                    if sb_user.external_user_id != dare_user_id:
                        sb_user.external_user_id = dare_user_id
                        sb_user.save(update_fields=['external_user_id'])
                        logger.info(f"Synced DARE user ID {dare_user_id} to SocraticBots user {dare_user_email}")
                except User.DoesNotExist:
                    # Create the user if not found
                    sb_user = User.objects.create_user(
                        email=dare_user_email,
                        name=dare_user_name,
                        external_user_id=dare_user_id
                    )
                    sb_user.set_unusable_password()
                    sb_user.save()
                    logger.info(f"Created SocraticBots user {dare_user_email} from DARE login (ID {dare_user_id})")

            return Response(login_response, status=status.HTTP_200_OK)
        except DareApiError as e:
            return Response(
                {'error': e.message},
                status=e.status_code or status.HTTP_400_BAD_REQUEST
            )

    except Exception as e:
        logger.error(f"Unexpected error in authenticate_with_dare: {str(e)}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    Proxy forgot-password request to DARE backend.
    The DARE backend sends the reset email with the correct callback URL
    based on the Origin/Referer headers set by DareAuthClient.
    """
    try:
        email = request.data.get('email') if hasattr(request.data, 'get') else None

        if not email:
            return Response(
                {'error': 'Email is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = auth_client.request_password_reset(email)
            return Response(result, status=status.HTTP_200_OK)
        except DareApiError as e:
            return Response(
                {'error': e.message},
                status=e.status_code or status.HTTP_400_BAD_REQUEST
            )

    except Exception as e:
        logger.error(f"Unexpected error in forgot_password: {str(e)}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def user_info(request):
    """
    Get current user information from SocraticBots database.
    JWT authentication guarantees we have an authenticated user.

    The platformRole is fetched from DARE backend to ensure it's always current,
    since role changes in DARE should be immediately reflected in SocraticBots.
    """
    user = request.user

    # Fetch fresh role from DARE backend
    token = get_bearer_token(request)
    if token:
        try:
            dare_user_info = auth_client.get_user_info(token)
            user._cached_role = dare_user_info.get('platformRole', 'USER')
            logger.info(f"Fetched DARE platformRole for user {user.email}: {user._cached_role}")
        except DareApiError as e:
            logger.warning(f"Could not fetch DARE user info, using default role: {e}")
            user._cached_role = 'USER'

    serializer = UserInfoSerializer(user)
    return Response(serializer.data, status=status.HTTP_200_OK)


# ============================================
# Notification Proxy Endpoints
# ============================================

from utils.dare_api import notifications_client

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_notifications(request):
    """
    Proxy endpoint to get notifications from DARE backend.
    Returns notifications targeted for SocraticBots platform.
    """
    try:
        # Get auth token from request
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                {'error': 'Invalid authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user_token = auth_header.split(' ')[1]
        status_filter = request.query_params.get('status')
        exclude_expired = request.query_params.get('exclude_expired', 'true').lower() == 'true'
        include_read = request.query_params.get('include_read', 'false').lower() == 'true'
        
        notifications = notifications_client.get_notifications(
            user_token=user_token,
            status=status_filter,
            exclude_expired=exclude_expired,
            include_read=include_read,
        )
        return Response(notifications)
        
    except DareApiError as e:
        logger.error(f"DARE API error fetching notifications: {e}")
        return Response(
            {'error': f'Failed to fetch notifications: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error fetching notifications: {e}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def get_notification_stats(request):
    """
    Proxy endpoint to get notification statistics from DARE backend.
    """
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                {'error': 'Invalid authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user_token = auth_header.split(' ')[1]
        stats = notifications_client.get_notification_stats(user_token=user_token)
        return Response(stats)
        
    except DareApiError as e:
        logger.error(f"DARE API error fetching notification stats: {e}")
        return Response(
            {'error': f'Failed to fetch notification stats: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error fetching notification stats: {e}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def mark_notification_read(request, notification_id):
    """
    Proxy endpoint to mark a notification as read in DARE backend.
    """
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                {'error': 'Invalid authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user_token = auth_header.split(' ')[1]
        result = notifications_client.mark_notification_as_read(
            notification_id=notification_id,
            user_token=user_token
        )
        return Response(result)
        
    except DareApiError as e:
        logger.error(f"DARE API error marking notification as read: {e}")
        return Response(
            {'error': f'Failed to mark notification as read: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error marking notification as read: {e}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def mark_all_notifications_read(request):
    """
    Proxy endpoint to mark all notifications as read in DARE backend.
    """
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                {'error': 'Invalid authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user_token = auth_header.split(' ')[1]
        result = notifications_client.mark_all_as_read(user_token=user_token)
        return Response(result)
        
    except DareApiError as e:
        logger.error(f"DARE API error marking all notifications as read: {e}")
        return Response(
            {'error': f'Failed to mark all notifications as read: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def clear_all_notifications(request):
    """
    Proxy endpoint to clear all notifications in DARE backend.
    """
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return Response(
                {'error': 'Invalid authorization header'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        user_token = auth_header.split(' ')[1]
        result = notifications_client.clear_all_notifications(user_token=user_token)
        return Response(result)
        
    except DareApiError as e:
        logger.error(f"DARE API error clearing notifications: {e}")
        return Response(
            {'error': f'Failed to clear notifications: {e.message}'},
            status=e.status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    except Exception as e:
        logger.error(f"Error clearing notifications: {e}")
        return Response(
            {'error': 'An unexpected error occurred'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
@api_view(['POST'])
@permission_classes([AllowAny])
@require_internal_key
def internal_delete_user(request):
    """Delete the Socratic Bots account linked to a DARE user.

    Called by the DARE backend during account expunge. Cascades to the
    user's bots, conversations, voice sessions, and other owned rows.
    """
    dare_user_id = request.data.get('dare_user_id')
    if not dare_user_id:
        return Response(
            {'error': 'dare_user_id is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    User = get_user_model()
    try:
        user = User.objects.get(external_user_id=dare_user_id)
    except User.DoesNotExist:
        return Response(
            {'error': 'No Socratic Bots account for this DARE user'},
            status=status.HTTP_404_NOT_FOUND,
        )

    email = user.email
    user.delete()
    logger.info(
        'Deleted Socratic Bots account %s (DARE user %s) via internal expunge',
        email, dare_user_id,
    )
    return Response({'detail': 'Socratic Bots account deleted'})
