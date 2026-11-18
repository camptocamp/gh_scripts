"""Report on oddities found in an exported organisation."""

from __future__ import annotations

from typing import Dict, List

from .models import OrgConfig


def build_report(config: OrgConfig) -> str:
    """Describe teams and repositories that are probably misconfigured.

    Only what is in ``config`` is considered: users are the ones granted direct
    access to a repository, so organisation members who are in no team and have
    no direct access are not listed. On a partial export the lists are
    incomplete.

    Returns
    -------
    str
        The report, one section per check.
    """
    empty_teams = sorted(
        t.name for t in config.teams if not t.maintainers and not t.members
    )

    team_users = {
        login.lower()
        for team in config.teams
        for login in (*team.maintainers, *team.members)
    }
    user_repos: Dict[str, List[str]] = {}
    for repo in config.repositories:
        for login in repo.users:
            if login.lower() not in team_users:
                user_repos.setdefault(login, []).append(repo.name)
    users_without_team = [
        f"{login} ({', '.join(sorted(repos))})"
        for login, repos in sorted(user_repos.items(), key=lambda i: i[0].lower())
    ]

    repos_without_team = sorted(r.name for r in config.repositories if not r.teams)
    repos_without_admin = sorted(
        r.name for r in config.repositories if "admin" not in r.teams.values()
    )

    sections = [
        ("Empty teams (no members, no maintainers)", empty_teams),
        ("Users without a team (repositories they can access)", users_without_team),
        ("Repositories without teams", repos_without_team),
        ("Repositories without an admin team", repos_without_admin),
    ]
    lines: List[str] = []
    for title, items in sections:
        lines.append(f"{title}: {len(items)}")
        lines.extend(f"  - {item}" for item in items)
        lines.append("")
    return "\n".join(lines)
