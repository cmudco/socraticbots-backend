#backend/users/models.py
import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

SUPERVISOR_ROLES = frozenset({'SUPERVISOR', 'SUPERADMIN'})
CREATOR_ROLES = frozenset({'CREATOR', 'RESEARCHER', 'SUPERVISOR', 'SUPERADMIN'})
STUDENT_ROLES = frozenset({'USER', 'SB_USER'})

class CustomUserManager(BaseUserManager):
    def create_user(self, email, name, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, name, password, **extra_fields)

class CustomUser(AbstractUser):
    # Remove username requirement and use email as primary identifier
    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    # Link to DARE user for synchronization
    external_user_id = models.IntegerField(null=True, blank=True, help_text="DARE user ID for sync")
    # Chunking preferences
    chunk_size = models.IntegerField(default=1000)
    overlap_size = models.IntegerField(default=100)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return self.email

    # --- Role properties (sourced from DARE JWT token) ---

    @property
    def platform_role(self):
        """
        Get user's platform role from cached JWT claims.
        Set by JWTAuthentication during request authentication.
        """
        if hasattr(self, '_cached_role'):
            return self._cached_role
        return 'USER'

    @property
    def is_supervisor_or_above(self) -> bool:
        """Check if the user has supervisor-level platform access from DARE."""
        return getattr(self, '_cached_is_superuser', self.is_superuser) or self.platform_role in SUPERVISOR_ROLES

    @property
    def is_creator(self):
        """Check if user has Creator role or higher (can create bots)."""
        return self.platform_role in CREATOR_ROLES

    @property
    def is_student(self):
        """Check if user has basic User/Student role (can only subscribe to bots)."""
        return self.platform_role in STUDENT_ROLES

    @property
    def has_supervisor_access_for_voice_agent(self) -> bool:
        """Supervisors can manage voice agents across all users."""
        return self.is_supervisor_or_above

