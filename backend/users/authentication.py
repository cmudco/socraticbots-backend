import jwt
import logging
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework import authentication
from rest_framework import exceptions

from utils.dare_api import auth_client, DareApiError

User = get_user_model()
logger = logging.getLogger(__name__)


class JWTAuthentication(authentication.BaseAuthentication):
    """
    Custom JWT authentication for DRF that works with DARE JWT tokens.
    This authentication class extracts the email claim from DARE JWT tokens,
    authenticates users from the SocraticBots database, and fetches
    the platform_role from DARE backend.

    The platform_role is fetched from DARE to ensure it's always current,
    since role changes in DARE should be immediately reflected in SocraticBots.
    """

    def authenticate(self, request):
        """
        Authenticate the request and return a two-tuple of (user, token).
        """
        # Get JWT token from Authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header.startswith('Bearer '):
            return None

        jwt_token = auth_header.replace('Bearer ', '')

        try:
            if not settings.DARE_SSO_JWT_KEY:
                logger.error("JWT Auth: SSO_JWT_KEY is not configured; cannot verify DARE tokens")
                return None
            decoded_token = jwt.decode(
                jwt_token, settings.DARE_SSO_JWT_KEY, algorithms=['HS256'], leeway=10
            )
            # DARE identifies users by email in its JWTs (shared SSO contract)
            email = decoded_token.get('email')
            if not email:
                return None

            try:
                user = User.objects.get(email__iexact=email, external_user_id__isnull=False)
                logger.debug(f"JWT Auth: Found user {user.email} by email")

                # Fetch platform_role from DARE backend
                try:
                    dare_user_info = auth_client.get_user_info(jwt_token)
                    platform_role = dare_user_info.get('platformRole', 'USER')
                    is_superuser = dare_user_info.get('isSuperuser', False)
                    logger.debug(f"JWT Auth: Fetched DARE platformRole for user {user.email}: {platform_role}")
                except DareApiError as e:
                    logger.warning(f"JWT Auth: Could not fetch DARE user info, using default role: {e}")
                    platform_role = 'USER'
                    is_superuser = False

                # Cache role information on the user object for permission checks
                user._cached_role = platform_role
                user._cached_is_superuser = is_superuser

                return (user, jwt_token)
            except User.DoesNotExist:
                logger.warning(f"JWT Auth: No DARE-linked user found with email={email}")
                return None
            except User.MultipleObjectsReturned:
                logger.error(f"JWT Auth: DUPLICATE USERS with email={email}. Database integrity issue - please clean up duplicates.")
                raise exceptions.AuthenticationFailed('Account error. Please contact support.')

        except jwt.ExpiredSignatureError:
            logger.warning("JWT Auth: Token has expired")
            raise exceptions.AuthenticationFailed('Token has expired')
        except jwt.InvalidTokenError as e:
            logger.warning(f"JWT Auth: Invalid token - {e}")
            raise exceptions.AuthenticationFailed('Invalid token')
        except Exception as e:
            logger.exception(f"JWT Auth: Unexpected error - {e}")
            return None

    def authenticate_header(self, request):
        """
        Return the authorization header that should be used for authentication.
        """
        return 'Bearer'
