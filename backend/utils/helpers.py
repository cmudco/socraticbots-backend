"""
Common helper functions.

Shared utilities used across multiple modules in the application.
"""
import re
from typing import Any


def slugify(text: str) -> str:
    """
    Convert text to URL-safe slug.

    Args:
        text: Text to convert

    Returns:
        Lowercase slug with special chars replaced by hyphens
    """
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    return slug.strip('-')


def get_user_display_name(user: Any) -> str:
    """
    Get display name for a user.

    Args:
        user: User object with first_name, last_name, and email attributes

    Returns:
        Full name if available, otherwise email username
    """
    if user.first_name or user.last_name:
        return f"{user.first_name} {user.last_name}".strip()
    # Fallback to email username
    return user.email.split('@')[0]
