"""Compute the changes needed to bring an organisation to its target state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from .config import dump_record, repository_to_dict
from .models import (
    LEVEL_ERROR,
    LEVEL_WARNING,
    Issue,
    OrgConfig,
    OrgState,
    Repository,
    Team,
)


@dataclass(frozen=True)
class Change:
    """A single modification to apply to the organisation."""

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class CreateTeam(Change):
    name: str
    parent: str = ""

    def describe(self) -> str:
        suffix = f" (parent: {self.parent})" if self.parent else ""
        return f"create team {self.name}{suffix}"


@dataclass(frozen=True)
class SetTeamParent(Change):
    name: str
    parent: str = ""

    def describe(self) -> str:
        if self.parent:
            return f"set parent of team {self.name} to {self.parent}"
        return f"remove parent of team {self.name}"


@dataclass(frozen=True)
class SetTeamMembership(Change):
    team: str
    login: str
    role: str
    previous_role: str = ""
    invite: bool = False

    def describe(self) -> str:
        if self.invite:
            return (
                f"invite {self.login} to the organization and add to team "
                f"{self.team} as {self.role}"
            )
        if self.previous_role:
            return (
                f"change role of {self.login} in team {self.team}: "
                f"{self.previous_role} -> {self.role}"
            )
        return f"add {self.login} to team {self.team} as {self.role}"


@dataclass(frozen=True)
class RemoveTeamMember(Change):
    team: str
    login: str

    def describe(self) -> str:
        return f"remove {self.login} from team {self.team}"


@dataclass(frozen=True)
class DeleteTeam(Change):
    name: str

    def describe(self) -> str:
        return f"delete team {self.name}"


@dataclass(frozen=True)
class CreateRepository(Change):
    repository: Repository

    def describe(self) -> str:
        repo = self.repository
        text = f"create repository {repo.name} ({repo.visibility})"
        if repo.forked:
            text += f" as a fork of {repo.forked}"
        details = []
        if repo.topics:
            details.append("topics: " + ", ".join(sorted(repo.topics)))
        if repo.teams:
            details.append(
                "teams: " + ", ".join(f"{t}={a}" for t, a in sorted(repo.teams.items()))
            )
        if repo.users:
            details.append(
                "users: " + ", ".join(f"{u}={a}" for u, a in sorted(repo.users.items()))
            )
        if details:
            text += " with " + "; ".join(details)
        return text


@dataclass(frozen=True)
class UpdateRepository(Change):
    name: str
    # (field, current value, wanted value)
    fields: Tuple[Tuple[str, object, object], ...]

    def describe(self) -> str:
        parts = [f"{f}: {old!r} -> {new!r}" for f, old, new in self.fields]
        return f"update repository {self.name} ({'; '.join(parts)})"


@dataclass(frozen=True)
class SetTeamAccess(Change):
    repository: str
    team: str
    access: str
    previous: str = ""

    def describe(self) -> str:
        if self.previous:
            return (
                f"change access of team {self.team} on {self.repository}: "
                f"{self.previous} -> {self.access}"
            )
        return f"grant team {self.team} {self.access} access on {self.repository}"


@dataclass(frozen=True)
class RemoveTeamAccess(Change):
    repository: str
    team: str

    def describe(self) -> str:
        return f"remove access of team {self.team} on {self.repository}"


@dataclass(frozen=True)
class SetUserAccess(Change):
    repository: str
    login: str
    access: str
    previous: str = ""

    def describe(self) -> str:
        if self.previous:
            return (
                f"change access of user {self.login} on {self.repository}: "
                f"{self.previous} -> {self.access}"
            )
        return f"grant user {self.login} {self.access} access on {self.repository}"


@dataclass(frozen=True)
class RemoveUserAccess(Change):
    repository: str
    login: str

    def describe(self) -> str:
        return f"remove access of user {self.login} on {self.repository}"


@dataclass(frozen=True)
class ArchiveRepository(Change):
    name: str

    def describe(self) -> str:
        return f"archive repository {self.name}"


@dataclass(frozen=True)
class UnarchiveRepository(Change):
    name: str

    def describe(self) -> str:
        return f"unarchive repository {self.name}"


@dataclass(frozen=True)
class DeleteRepository(Change):
    name: str

    def describe(self) -> str:
        return f"delete repository {self.name}"


@dataclass(frozen=True)
class RemoveOrgMember(Change):
    login: str

    def describe(self) -> str:
        return f"remove {self.login} from the organization"


@dataclass(frozen=True)
class RemoveOutsideCollaborator(Change):
    login: str

    def describe(self) -> str:
        return f"remove outside collaborator {self.login} from all repositories"


@dataclass
class Plan:
    """The ordered changes to apply, and the problems found while computing them."""

    changes: List[Change] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)


def _lower(logins) -> Set[str]:
    return {login.lower() for login in logins}


def compute_changes(
    desired: OrgConfig,
    actual: OrgState,
    prune_teams: bool = False,
    prune_repos: bool = False,
    prune_users: bool = False,
) -> Plan:
    """Compare the target configuration with the current state.

    Parameters
    ----------
    desired: OrgConfig
        The (validated) target configuration.
    actual: OrgState
        The current state of the organisation.
    prune_teams: bool
        Delete the teams which are not in the configuration.
    prune_repos: bool
        Delete the repositories which are not in the configuration.
    prune_users: bool
        Remove the members which belong to no configured team (organization
        owners are never removed) and the outside collaborators which are
        not listed in any repository.

    Returns
    -------
    Plan
        The changes, in an order which can be applied sequentially, and the
        warnings and errors found on the way.
    """
    return _Differ(desired, actual, prune_teams, prune_repos, prune_users).run()


class _Differ:
    def __init__(
        self,
        desired: OrgConfig,
        actual: OrgState,
        prune_teams: bool,
        prune_repos: bool,
        prune_users: bool,
    ) -> None:
        self.desired = desired
        self.actual = actual
        self.prune_teams = prune_teams
        self.prune_repos = prune_repos
        self.prune_users = prune_users
        self.issues: List[Issue] = []
        self.team_changes: List[Change] = []
        self.membership_changes: List[Change] = []
        self.repo_create: List[Change] = []
        self.repo_unarchive: List[Change] = []
        self.repo_update: List[Change] = []
        self.repo_archive: List[Change] = []
        self.deletions: List[Change] = []
        self.actual_teams: Dict[str, Team] = {t.name: t for t in actual.config.teams}
        self.actual_repos: Dict[str, Repository] = {
            r.name: r for r in actual.config.repositories
        }

    def run(self) -> Plan:
        self._diff_teams()
        self._diff_repositories()
        self._diff_unmanaged()
        if self.prune_users:
            self._diff_users()
        changes = (
            self.team_changes
            + self.membership_changes
            + self.repo_create
            + self.repo_unarchive
            + self.repo_update
            + self.repo_archive
            + self.deletions
        )
        return Plan(changes=changes, issues=self.issues)

    def _issue(self, level: str, message: str) -> None:
        self.issues.append(Issue(level, message))

    # -- teams ---------------------------------------------------------

    def _ordered_desired_teams(self) -> List[Team]:
        """Return the teams, parents before children."""
        by_name = {t.name: t for t in self.desired.teams}
        ordered: List[Team] = []
        done: Set[str] = set()

        def visit(team: Team, stack: Tuple[str, ...]) -> None:
            if team.name in done or team.name in stack:
                return
            parent = by_name.get(team.parent)
            if parent is not None:
                visit(parent, stack + (team.name,))
            done.add(team.name)
            ordered.append(team)

        for team in sorted(by_name.values(), key=lambda t: t.name):
            visit(team, ())
        return ordered

    def _diff_teams(self) -> None:
        invites: List[SetTeamMembership] = []
        members = _lower(self.actual.members)
        pending = _lower(self.actual.pending_invitations)
        for team in self._ordered_desired_teams():
            current = self.actual_teams.get(team.name)
            if current is None:
                self.team_changes.append(CreateTeam(team.name, team.parent))
            elif current.parent != team.parent:
                self.team_changes.append(SetTeamParent(team.name, team.parent))

            wanted = {login.lower(): (login, "member") for login in team.members}
            wanted.update(
                {login.lower(): (login, "maintainer") for login in team.maintainers}
            )
            existing: Dict[str, Tuple[str, str]] = {}
            if current is not None:
                existing = {
                    login.lower(): (login, "member") for login in current.members
                }
                existing.update(
                    {
                        login.lower(): (login, "maintainer")
                        for login in current.maintainers
                    }
                )

            for key in sorted(wanted):
                login, role = wanted[key]
                if key in existing:
                    previous = existing[key][1]
                    if previous != role:
                        self.membership_changes.append(
                            SetTeamMembership(team.name, login, role, previous)
                        )
                elif key in members:
                    self.membership_changes.append(
                        SetTeamMembership(team.name, login, role)
                    )
                elif key in pending:
                    continue
                else:
                    invites.append(
                        SetTeamMembership(team.name, login, role, invite=True)
                    )
            for key in sorted(existing):
                if key not in wanted:
                    self.membership_changes.append(
                        RemoveTeamMember(team.name, existing[key][0])
                    )

        self.membership_changes.extend(self._allocate_seats(invites))

        if self.prune_teams:
            wanted_names = {t.name for t in self.desired.teams}
            for name in sorted(set(self.actual_teams) - wanted_names):
                self.deletions.append(DeleteTeam(name))

    def _allocate_seats(
        self, invites: List[SetTeamMembership]
    ) -> List[SetTeamMembership]:
        """Keep the invitations for which a seat is available."""
        logins = sorted({i.login.lower() for i in invites})
        if not logins:
            return []
        seats = self.actual.seats
        if seats is None:
            self._issue(
                LEVEL_WARNING,
                f"seats of the organization are unknown: {len(logins)} "
                "invitation(s) needed, availability not checked",
            )
            return invites
        available = seats.available
        if len(logins) <= available:
            return invites
        missing = len(logins) - available
        self._issue(
            LEVEL_WARNING,
            f"not enough seats in the organization: {len(logins)} invitation(s) "
            f"needed, {available} seat(s) available; {missing} additional "
            "seat(s) required",
        )
        allowed = set(logins[:available])
        for key in logins[available:]:
            teams = sorted({i.team for i in invites if i.login.lower() == key})
            login = next(i.login for i in invites if i.login.lower() == key)
            self._issue(
                LEVEL_WARNING,
                f"no seat available: {login} is not invited "
                f"(wanted in team(s) {', '.join(teams)})",
            )
        return [i for i in invites if i.login.lower() in allowed]

    # -- repositories --------------------------------------------------

    def _diff_repositories(self) -> None:
        for repo in sorted(self.desired.repositories, key=lambda r: r.name):
            current = self.actual_repos.get(repo.name)
            if current is None:
                self.repo_create.append(CreateRepository(repo))
                if repo.archived:
                    self.repo_archive.append(ArchiveRepository(repo.name))
                continue

            if (repo.forked or "").lower() != (current.forked or "").lower():
                self._issue(
                    LEVEL_ERROR,
                    f"repository {repo.name}: fork status cannot be changed "
                    f"(configured: {repo.forked or 'not a fork'}, "
                    f"actual: {current.forked or 'not a fork'}); skipped",
                )
                continue

            changes = self._repository_changes(repo, current)
            if current.archived and not repo.archived:
                self.repo_unarchive.append(UnarchiveRepository(repo.name))
                self.repo_update.extend(changes)
            elif current.archived:
                if changes:
                    self._issue(
                        LEVEL_WARNING,
                        f"repository {repo.name} is archived, skipped changes: "
                        + "; ".join(c.describe() for c in changes),
                    )
            else:
                self.repo_update.extend(changes)
                if repo.archived:
                    self.repo_archive.append(ArchiveRepository(repo.name))

    def _repository_changes(
        self, repo: Repository, current: Repository
    ) -> List[Change]:
        changes: List[Change] = []
        fields = []
        if repo.visibility != current.visibility:
            fields.append(("visibility", current.visibility, repo.visibility))
        if repo.description != current.description:
            fields.append(("description", current.description, repo.description))
        if set(repo.topics) != set(current.topics):
            fields.append(("topics", sorted(current.topics), sorted(repo.topics)))
        if fields:
            changes.append(UpdateRepository(repo.name, tuple(fields)))

        for team, access in sorted(repo.teams.items()):
            previous = current.teams.get(team, "")
            if previous != access:
                changes.append(SetTeamAccess(repo.name, team, access, previous))
        for team in sorted(set(current.teams) - set(repo.teams)):
            changes.append(RemoveTeamAccess(repo.name, team))

        current_users = {u.lower(): (u, a) for u, a in current.users.items()}
        wanted_users = {u.lower() for u in repo.users}
        for login, access in sorted(repo.users.items()):
            previous = current_users.get(login.lower(), ("", ""))[1]
            if previous != access:
                changes.append(SetUserAccess(repo.name, login, access, previous))
        for key in sorted(set(current_users) - wanted_users):
            changes.append(RemoveUserAccess(repo.name, current_users[key][0]))
        return changes

    def _diff_unmanaged(self) -> None:
        wanted = {r.name for r in self.desired.repositories}
        for name in sorted(set(self.actual_repos) - wanted):
            if self.prune_repos:
                self.deletions.append(DeleteRepository(name))
                continue
            content = dump_record(repository_to_dict(self.actual_repos[name]))
            self._issue(
                LEVEL_WARNING,
                f"repository {name} exists in the organization but is not in the "
                f"configuration; add a file with this content:\n{content}",
            )

    # -- users ---------------------------------------------------------

    def _diff_users(self) -> None:
        if not self.desired.teams:
            self._issue(
                LEVEL_ERROR,
                "no team in the configuration: refusing to prune users",
            )
            return
        in_teams: Set[str] = set()
        for team in self.desired.teams:
            in_teams |= _lower(team.maintainers) | _lower(team.members)
        owners = _lower(self.actual.owners)
        for login in sorted(self.actual.members, key=str.lower):
            if login.lower() not in in_teams and login.lower() not in owners:
                self.deletions.append(RemoveOrgMember(login))

        listed: Set[str] = set()
        for repo in self.desired.repositories:
            listed |= _lower(repo.users)
        for login in sorted(self.actual.outside_collaborators, key=str.lower):
            if login.lower() not in listed:
                self.deletions.append(RemoveOutsideCollaborator(login))
