"""Semantic validation of an organisation configuration."""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

from .models import (
    ACCESS_LEVELS,
    LEVEL_ERROR,
    LEVEL_WARNING,
    VISIBILITIES,
    Issue,
    OrgConfig,
    Repository,
    Team,
)

FORK_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


def validate(config: OrgConfig) -> List[Issue]:
    """Check the rules of every record and return the problems found."""
    issues: List[Issue] = []
    issues.extend(_check_duplicates("team", [(t.name, t.source) for t in config.teams]))
    issues.extend(
        _check_duplicates(
            "repository", [(r.name, r.source) for r in config.repositories]
        )
    )

    teams_by_name: Dict[str, Team] = {}
    for team in config.teams:
        teams_by_name.setdefault(team.name, team)

    for team in config.teams:
        issues.extend(_validate_team(team, teams_by_name))
    issues.extend(_check_parent_cycles(teams_by_name))
    for repo in config.repositories:
        issues.extend(_validate_repository(repo, teams_by_name))
    return issues


def _check_duplicates(kind: str, entries: List[tuple]) -> List[Issue]:
    counts = Counter(name for name, _ in entries)
    issues = []
    for name, source in entries:
        if counts[name] > 1:
            issues.append(
                Issue(
                    LEVEL_ERROR,
                    f"{kind} name {name!r} is defined more than once",
                    source,
                )
            )
    return issues


def _validate_team(team: Team, teams_by_name: Dict[str, Team]) -> List[Issue]:
    issues = []
    if not team.maintainers:
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"team {team.name!r} must have at least one maintainer",
                team.source,
            )
        )
    for login in sorted(set(team.maintainers) & set(team.members)):
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"team {team.name!r}: {login!r} cannot be both maintainer and member",
                team.source,
            )
        )
    if team.parent and team.parent not in teams_by_name:
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"team {team.name!r}: parent team {team.parent!r} is not defined",
                team.source,
            )
        )
    return issues


def _check_parent_cycles(teams_by_name: Dict[str, Team]) -> List[Issue]:
    issues = []
    reported = set()
    for start in teams_by_name.values():
        seen = [start.name]
        current = start
        while current.parent and current.parent in teams_by_name:
            if current.parent in seen:
                cycle = seen[seen.index(current.parent) :]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    issues.append(
                        Issue(
                            LEVEL_ERROR,
                            "team parent cycle: " + " -> ".join(cycle + [cycle[0]]),
                            start.source,
                        )
                    )
                break
            seen.append(current.parent)
            current = teams_by_name[current.parent]
    return issues


def _validate_repository(
    repo: Repository, teams_by_name: Dict[str, Team]
) -> List[Issue]:
    issues = []
    name = repo.name

    if not repo.visibility:
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"repository {name!r}: 'visibility' is mandatory",
                repo.source,
            )
        )
    elif repo.visibility not in VISIBILITIES:
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"repository {name!r}: visibility must be 'public' or 'private', "
                f"got {repo.visibility!r}",
                repo.source,
            )
        )

    if repo.forked and not FORK_RE.match(repo.forked):
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"repository {name!r}: 'forked' must be 'owner/reponame', "
                f"got {repo.forked!r}",
                repo.source,
            )
        )

    for team_name, access in repo.teams.items():
        if team_name not in teams_by_name:
            issues.append(
                Issue(
                    LEVEL_ERROR,
                    f"repository {name!r}: team {team_name!r} is not defined",
                    repo.source,
                )
            )
        issues.extend(_check_access("team", team_name, access, repo))
    for login, access in repo.users.items():
        issues.extend(_check_access("user", login, access, repo))

    if "admin" not in repo.teams.values():
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"repository {name!r} must have at least one admin team",
                repo.source,
            )
        )

    if repo.users:
        issues.append(
            Issue(
                LEVEL_WARNING,
                f"repository {name!r} grants access to individual users "
                f"({', '.join(sorted(repo.users))}); prefer teams",
                repo.source,
            )
        )
    return issues


def _check_access(kind: str, who: str, access: str, repo: Repository) -> List[Issue]:
    if access in ACCESS_LEVELS:
        return []
    return [
        Issue(
            LEVEL_ERROR,
            f"repository {repo.name!r}: invalid access right {access!r} for {kind} "
            f"{who!r} (expected one of {', '.join(ACCESS_LEVELS)})",
            repo.source,
        )
    ]
