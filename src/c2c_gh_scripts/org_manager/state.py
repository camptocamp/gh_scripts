"""Read the current state of a GitHub organisation as an ``OrgConfig``."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    ACCESS_LEVELS,
    LEVEL_WARNING,
    Issue,
    OrgConfig,
    OrgState,
    Repository,
    SeatInfo,
    Team,
)

# GitHub API role names (collaborators) -> configuration access levels
ROLE_TO_ACCESS = {
    "read": "pull",
    "triage": "triage",
    "write": "push",
    "maintain": "maintain",
    "admin": "admin",
}
PERMISSION_ORDER = ("admin", "maintain", "push", "triage", "pull")


def _team_access(permission: Optional[str]) -> Optional[str]:
    if permission in ACCESS_LEVELS:
        return permission
    return ROLE_TO_ACCESS.get(permission or "")


def _user_access(user: Any) -> Optional[str]:
    role = getattr(user, "role_name", None)
    if role:
        return ROLE_TO_ACCESS.get(role, role if role in ACCESS_LEVELS else None)
    permissions = getattr(user, "permissions", None)
    if permissions is not None:
        for level in PERMISSION_ORDER:
            if getattr(permissions, level, False):
                return level
    return None


def load_github_state(
    gh: Any,
    org_name: str,
    repo_names: Iterable[str] = (),
    team_names: Iterable[str] = (),
) -> Tuple[OrgConfig, List[Issue]]:
    """Build an ``OrgConfig`` describing the current state of an organisation.

    Parameters
    ----------
    gh: github.Github
        Authenticated GitHub client.
    org_name: str
        Name of the organisation.
    repo_names: Iterable[str]
        Only load these repositories. All repositories when empty.
    team_names: Iterable[str]
        Only load these teams. All teams when empty.

    Returns
    -------
    tuple[OrgConfig, list[Issue]]
        The current state, and warnings about anything that cannot be
        represented in the configuration format.
    """
    return _load_config(gh.get_organization(org_name), org_name, repo_names, team_names)


def load_org_state(gh: Any, org_name: str) -> Tuple[OrgState, List[Issue]]:
    """Read teams, repositories, members and seats of an organisation.

    Returns
    -------
    tuple[OrgState, list[Issue]]
        The current state, and warnings about anything that cannot be
        represented in the configuration format.
    """
    org = gh.get_organization(org_name)
    config, issues = _load_config(org, org_name, (), ())
    state = OrgState(
        config=config,
        members=[u.login for u in org.get_members()],
        owners=[u.login for u in org.get_members(role="admin")],
        outside_collaborators=[u.login for u in org.get_outside_collaborators()],
        pending_invitations=[
            i.login for i in org.invitations() if getattr(i, "login", None)
        ],
    )
    plan = getattr(org, "plan", None)
    seats = getattr(plan, "seats", None)
    if seats:
        state.seats = SeatInfo(total=seats, filled=getattr(plan, "filled_seats", 0))
    return state, issues


def _load_config(
    org: Any,
    org_name: str,
    repo_names: Iterable[str],
    team_names: Iterable[str],
) -> Tuple[OrgConfig, List[Issue]]:
    issues: List[Issue] = []
    config = OrgConfig()

    wanted_teams = set(team_names)
    seen_teams = set()
    for gh_team in org.get_teams():
        if wanted_teams and gh_team.name not in wanted_teams:
            continue
        seen_teams.add(gh_team.name)
        config.teams.append(_load_team(gh_team))
    for missing in sorted(wanted_teams - seen_teams):
        issues.append(Issue(LEVEL_WARNING, f"team {missing!r} not found in {org_name}"))

    wanted_repos = set(repo_names)
    seen_repos = set()
    for gh_repo in org.get_repos():
        if wanted_repos and gh_repo.name not in wanted_repos:
            continue
        seen_repos.add(gh_repo.name)
        config.repositories.append(_load_repository(gh_repo, issues))
    for missing in sorted(wanted_repos - seen_repos):
        issues.append(
            Issue(LEVEL_WARNING, f"repository {missing!r} not found in {org_name}")
        )

    return config, issues


def _load_team(gh_team: Any) -> Team:
    parent = gh_team.parent.name if gh_team.parent else ""
    return Team(
        name=gh_team.name,
        maintainers=sorted(u.login for u in gh_team.get_members(role="maintainer")),
        members=sorted(u.login for u in gh_team.get_members(role="member")),
        parent=parent,
    )


def _load_repository(gh_repo: Any, issues: List[Issue]) -> Repository:
    name = gh_repo.name
    visibility = getattr(gh_repo, "visibility", None) or (
        "private" if gh_repo.private else "public"
    )
    if visibility not in ("public", "private"):
        issues.append(
            Issue(
                LEVEL_WARNING,
                f"repository {name!r} has visibility {visibility!r}, "
                "exported as 'private'",
            )
        )
        visibility = "private"

    teams: Dict[str, str] = {}
    for gh_team in gh_repo.get_teams():
        access = _team_access(gh_team.permission)
        if access is None:
            issues.append(
                Issue(
                    LEVEL_WARNING,
                    f"repository {name!r}: team {gh_team.name!r} has unsupported "
                    f"permission {gh_team.permission!r}, ignored",
                )
            )
            continue
        teams[gh_team.name] = access

    users: Dict[str, str] = {}
    for user in gh_repo.get_collaborators(affiliation="direct"):
        access = _user_access(user)
        if access is None:
            issues.append(
                Issue(
                    LEVEL_WARNING,
                    f"repository {name!r}: user {user.login!r} has an unsupported "
                    "role, ignored",
                )
            )
            continue
        users[user.login] = access

    forked = ""
    if gh_repo.fork and gh_repo.parent is not None:
        forked = gh_repo.parent.full_name

    return Repository(
        name=name,
        visibility=visibility,
        description=gh_repo.description or "",
        topics=sorted(gh_repo.get_topics()),
        teams=dict(sorted(teams.items())),
        users=dict(sorted(users.items())),
        archived=bool(gh_repo.archived),
        forked=forked,
    )
