# Data migration: Sync SB users to DARE backend with smart role assignment.
# This runs WHILE is_professor column still exists, BEFORE it is removed in 0004.
#
# Requires:
#   - DARE backend running with migrations 0023+ applied (platform_role field exists)
#   - DARE_BACKEND_URL and DARE_INTERNAL_KEY set in environment
#
# Smart role assignment logic (handled by DARE endpoint):
#   - Professor + has DARE access → RESEARCHER (DARE + SB creator)
#   - Professor + no DARE access → CREATOR (SB only, can create)
#   - Student + has DARE access → USER (DARE + SB consumer)
#   - Student + no DARE access → SB_USER (SB only, consumer)
#
# Deployment order:
#   1. Apply DARE migrations (0023 adds platform_role, 0024 sets superadmins)
#   2. Start DARE backend
#   3. Apply SB migrations (0003 migrates users, 0004 removes is_professor column)

import os

from django.db import migrations


def migrate_users_to_dare(apps, schema_editor):
    """
    Sync all SB users with external_user_id to DARE with smart role assignment.
    The DARE endpoint determines the correct role based on:
    - is_professor flag from SB
    - Whether user already has DARE access (existing role)
    """
    import requests

    CustomUser = apps.get_model('users', 'CustomUser')

    # Get all users with external_user_id (linked to DARE)
    users_to_sync = CustomUser.objects.filter(external_user_id__isnull=False)

    if not users_to_sync.exists():
        print("  No users with external_user_id found to migrate.")
        return

    dare_url = os.environ.get('DARE_BACKEND_URL', 'http://127.0.0.1:8000')
    internal_key = os.environ.get('DARE_INTERNAL_KEY', 'local-dev-internal-key')

    endpoint = f"{dare_url}/users/api/internal/set-role/"
    migrated = []
    failed = []
    skipped = []

    for user in users_to_sync:
        try:
            # Use smart role assignment - DARE will determine the correct role
            # based on is_professor and whether user has existing DARE access
            response = requests.post(
                endpoint,
                json={
                    'user_id': user.external_user_id,
                    'is_professor': user.is_professor,  # Let DARE decide the role
                },
                headers={'X-Internal-Key': internal_key},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                # Handle both camelCase and snake_case responses
                old_role = data.get('oldRole') or data.get('old_role', '?')
                new_role = data.get('newRole') or data.get('new_role', '?')
                had_dare = data.get('hadDareAccess') or data.get('had_dare_access', False)

                status_msg = (
                    f"{user.email} (DARE id={user.external_user_id}, "
                    f"is_professor={user.is_professor}, had_dare_access={had_dare}): "
                    f"{old_role} -> {new_role}"
                )

                if old_role == new_role:
                    skipped.append(status_msg)
                else:
                    migrated.append(status_msg)
            else:
                failed.append(
                    f"{user.email} (DARE id={user.external_user_id}): "
                    f"HTTP {response.status_code} - {response.text}"
                )
        except requests.ConnectionError:
            msg = (
                f"Cannot connect to DARE backend at {dare_url}. "
                f"Ensure DARE is running with migrations 0023+ applied."
            )
            raise RuntimeError(msg)
        except requests.RequestException as e:
            failed.append(f"{user.email}: {str(e)}")

    # Print summary
    if migrated:
        print(f"  Migrated {len(migrated)} user(s) with role changes:")
        for m in migrated:
            print(f"    {m}")

    if skipped:
        print(f"  Skipped {len(skipped)} user(s) (role unchanged):")
        for s in skipped:
            print(f"    {s}")

    if failed:
        print(f"  WARNING: {len(failed)} user(s) failed to migrate:")
        for f in failed:
            print(f"    {f}")
        raise RuntimeError(
            f"Failed to migrate {len(failed)} user(s) to DARE. "
            f"Fix the issues above and re-run the migration."
        )


def reverse_migrate_users(apps, schema_editor):
    """
    Reverse: Reset users back to USER role in DARE.
    Note: This is best-effort and requires DARE backend to be running.
    """
    import requests

    CustomUser = apps.get_model('users', 'CustomUser')
    users_to_revert = CustomUser.objects.filter(external_user_id__isnull=False)

    dare_url = os.environ.get('DARE_BACKEND_URL', 'http://127.0.0.1:8000')
    internal_key = os.environ.get('DARE_INTERNAL_KEY', 'local-dev-internal-key')
    endpoint = f"{dare_url}/users/api/internal/set-role/"

    for user in users_to_revert:
        try:
            requests.post(
                endpoint,
                json={
                    'user_id': user.external_user_id,
                    'platform_role': 'USER'  # Reset to default
                },
                headers={'X-Internal-Key': internal_key},
                timeout=10
            )
        except requests.RequestException:
            pass  # Best-effort reversal


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_user_chunk_settings'),
    ]

    operations = [
        migrations.RunPython(
            migrate_users_to_dare,
            reverse_migrate_users,
        ),
    ]
