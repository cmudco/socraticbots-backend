# voice/access.py
"""
Access resolution for voice agents.

Implements highest-privilege-wins logic across supervisor, owner,
team membership, agent membership, and student access scopes.

Priority order (high → low):
  supervisor > owner > manager > admin > reviewer > student > None
"""

from django.db.models import Q

from voice.constants import ROLE_PRIORITY, VoiceTeamRole
from voice.models import VoiceAgent, VoiceTeamMembership, VoiceAgentMembership, VoiceAgentAccess

# Canonical access level names returned by resolve_access().
# These are ordered by privilege (highest first).
ACCESS_SUPERVISOR = 'supervisor'
ACCESS_OWNER = 'owner'
ACCESS_MANAGER = 'manager'
ACCESS_ADMIN = 'admin'
ACCESS_REVIEWER = 'reviewer'
ACCESS_STUDENT = 'student'

# Numeric priority for access levels (higher = more privilege)
ACCESS_PRIORITY = {
    ACCESS_STUDENT: 0,
    ACCESS_REVIEWER: 1,
    ACCESS_ADMIN: 2,
    ACCESS_MANAGER: 3,
    ACCESS_OWNER: 4,
    ACCESS_SUPERVISOR: 5,
}

# Permission sets keyed by access level
CAN_EDIT = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER, ACCESS_ADMIN}
CAN_DELETE = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER}
CAN_MANAGE_ACCESS = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER}
CAN_VIEW_TRANSCRIPTS = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER, ACCESS_ADMIN, ACCESS_REVIEWER}
CAN_LAUNCH_EXAM = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER, ACCESS_ADMIN, ACCESS_REVIEWER, ACCESS_STUDENT}
CAN_VIEW_AGENT = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER, ACCESS_ADMIN, ACCESS_REVIEWER, ACCESS_STUDENT}

# Staff levels bypass the one-attempt limit for exam launches
STAFF_ACCESS_LEVELS = {ACCESS_SUPERVISOR, ACCESS_OWNER, ACCESS_MANAGER, ACCESS_ADMIN, ACCESS_REVIEWER}


def resolve_access(user, agent):
    """
    Determine the effective access level for a user on a voice agent.

    Returns one of the ACCESS_* constants, or None if no access.
    Uses highest-privilege-wins: checks all scopes and returns the highest.
    """
    if not user or not user.is_authenticated:
        return None

    # 1. Supervisor / Superadmin
    if user.is_supervisor_or_above:
        return ACCESS_SUPERVISOR

    # 2. Owner
    if agent.user_id == user.pk:
        return ACCESS_OWNER

    # 3. Collect membership roles (both scopes)
    best_priority = -1
    best_level = None

    # Team-level membership (if agent belongs to a team)
    if agent.team_id:
        team_membership = VoiceTeamMembership.objects.filter(
            team_id=agent.team_id, user=user
        ).values_list('role', flat=True).first()

        if team_membership:
            role_priority = ROLE_PRIORITY.get(team_membership, 0)
            if role_priority > best_priority:
                best_priority = role_priority
                # Map role string to access level
                best_level = team_membership  # manager/admin/reviewer map 1:1

    # Agent-level membership
    agent_membership = VoiceAgentMembership.objects.filter(
        agent=agent, user=user
    ).values_list('role', flat=True).first()

    if agent_membership:
        role_priority = ROLE_PRIORITY.get(agent_membership, 0)
        if role_priority > best_priority:
            best_priority = role_priority
            best_level = agent_membership

    if best_level:
        return best_level

    # 4. Student access (redeemed access code)
    if VoiceAgentAccess.objects.filter(agent=agent, user=user).exists():
        return ACCESS_STUDENT

    return None


def get_permissions_dict(access_level):
    """
    Convert an access level into a permissions dictionary for serializers.
    """
    if not access_level:
        return {
            'canEdit': False,
            'canDelete': False,
            'canManageAccess': False,
            'canViewTranscripts': False,
            'canLaunchExam': False,
            'isStaff': False,
            'accessLevel': None,
        }

    return {
        'canEdit': access_level in CAN_EDIT,
        'canDelete': access_level in CAN_DELETE,
        'canManageAccess': access_level in CAN_MANAGE_ACCESS,
        'canViewTranscripts': access_level in CAN_VIEW_TRANSCRIPTS,
        'canLaunchExam': access_level in CAN_LAUNCH_EXAM,
        'isStaff': access_level in STAFF_ACCESS_LEVELS,
        'accessLevel': access_level,
    }


def is_voice_team_manager(user) -> bool:
    """Check if user is a manager of any voice team."""
    return VoiceTeamMembership.objects.filter(
        user=user, role=VoiceTeamRole.MANAGER
    ).exists()


def can_create_voice_agents(user) -> bool:
    """Creators can create personal agents; supervisors/team managers can also create team agents."""
    if not user or not user.is_authenticated:
        return False
    return user.is_creator or user.is_supervisor_or_above or is_voice_team_manager(user)


def user_can_access_agent(user, agent):
    """Shortcut: returns True if the user has any access level."""
    return resolve_access(user, agent) is not None


def get_accessible_agents_queryset(user):
    """
    Return a queryset of VoiceAgent IDs the user can access,
    combining ownership, team membership, agent membership, and student access.

    Supervisors should be handled separately (they see all agents).
    """
    if user.is_supervisor_or_above:
        return VoiceAgent.objects.filter(is_deleted=False)

    q = Q(user=user)  # Owner

    # Teams the user is a member of
    team_ids = VoiceTeamMembership.objects.filter(
        user=user
    ).values_list('team_id', flat=True)
    if team_ids:
        q |= Q(team_id__in=team_ids)

    # Agents the user has direct membership on
    agent_ids = VoiceAgentMembership.objects.filter(
        user=user
    ).values_list('agent_id', flat=True)
    if agent_ids:
        q |= Q(pk__in=agent_ids)

    # Student access
    student_agent_ids = VoiceAgentAccess.objects.filter(
        user=user
    ).values_list('agent_id', flat=True)
    if student_agent_ids:
        q |= Q(pk__in=student_agent_ids)

        # Auto-expand: include agents by the same creator with the same access code.
        # This lets a single code grant access to multiple exams by one creator.
        creator_code_pairs = VoiceAgent.objects.filter(
            pk__in=student_agent_ids,
            access_code__isnull=False,
        ).exclude(
            access_code=''
        ).values_list('user_id', 'access_code').distinct()

        for creator_id, code in creator_code_pairs:
            q |= Q(user_id=creator_id, access_code=code)

    return VoiceAgent.objects.filter(q, is_deleted=False).distinct()
