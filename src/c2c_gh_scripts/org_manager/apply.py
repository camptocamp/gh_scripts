"""Apply a plan of changes to a GitHub organisation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from github import GithubException, RateLimitExceededException

from . import diff
from .diff import Change


class ApplyError(Exception):
    """A change cannot be applied because something it needs is missing."""


@dataclass
class Failure:
    change: Change
    error: Exception


class Executor:
    """Execute changes with PyGithub.

    Failures are logged and collected so that the remaining changes are
    still applied. Rate limit errors are retried, after waiting.

    Parameters
    ----------
    gh: github.Github
        Authenticated GitHub client.
    org_name: str
        Name of the organisation.
    logger: logging.Logger
        Logger used to report each change.
    sleep: Callable[[float], None]
        Function used to wait before a retry.
    max_retries: int
        Number of retries on a rate limit error.
    """

    def __init__(
        self,
        gh: Any,
        org_name: str,
        logger: logging.Logger,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
    ) -> None:
        self.gh = gh
        self.org_name = org_name
        self.logger = logger
        self.sleep = sleep
        self.max_retries = max_retries
        self._org: Any = None
        self._teams: Optional[Dict[str, Any]] = None
        self._repos: Dict[str, Any] = {}
        self._users: Dict[str, Any] = {}

    def execute(self, changes: List[Change]) -> List[Failure]:
        """Apply the changes in order and return the ones which failed."""
        failures: List[Failure] = []
        for change in changes:
            try:
                self._dispatch(change)
            except (GithubException, ApplyError) as exc:
                self.logger.error("failed: %s: %s", change.describe(), _error_text(exc))
                failures.append(Failure(change, exc))
            else:
                self.logger.info("done: %s", change.describe())
        return failures

    # -- helpers -------------------------------------------------------

    def _dispatch(self, change: Change) -> None:
        handler = getattr(self, f"_do_{type(change).__name__}", None)
        if handler is None:
            raise ApplyError(f"unsupported change {type(change).__name__}")
        handler(change)

    def _call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except RateLimitExceededException as exc:
                if attempt == self.max_retries:
                    raise
                delay = _retry_delay(exc, attempt)
                self.logger.warning("rate limited, retrying in %.0fs", delay)
                self.sleep(delay)

    @property
    def org(self) -> Any:
        if self._org is None:
            self._org = self._call(self.gh.get_organization, self.org_name)
        return self._org

    def _team(self, name: str) -> Any:
        if self._teams is None:
            self._teams = {
                t.name: t for t in self._call(lambda: list(self.org.get_teams()))
            }
        try:
            return self._teams[name]
        except KeyError:
            raise ApplyError(f"team {name!r} does not exist") from None

    def _repo(self, name: str) -> Any:
        if name not in self._repos:
            self._repos[name] = self._call(self.org.get_repo, name)
        return self._repos[name]

    def _user(self, login: str) -> Any:
        if login not in self._users:
            self._users[login] = self._call(self.gh.get_user, login)
        return self._users[login]

    # -- teams ---------------------------------------------------------

    def _parent_id(self, parent: str) -> Optional[int]:
        return self._team(parent).id if parent else None

    def _do_CreateTeam(self, change: diff.CreateTeam) -> None:
        kwargs: Dict[str, Any] = {"privacy": "closed"}
        if change.parent:
            kwargs["parent_team_id"] = self._parent_id(change.parent)
        team = self._call(self.org.create_team, change.name, **kwargs)
        if self._teams is not None:
            self._teams[change.name] = team
        keep = {login.lower() for login in change.logins}
        for member in self._call(lambda: list(team.get_members())):
            if member.login.lower() not in keep:
                self._call(team.remove_membership, member)

    def _do_SetTeamParent(self, change: diff.SetTeamParent) -> None:
        team = self._team(change.name)
        self._call(
            team.edit, change.name, parent_team_id=self._parent_id(change.parent)
        )

    def _do_SetTeamMembership(self, change: diff.SetTeamMembership) -> None:
        team = self._team(change.team)
        self._call(team.add_membership, self._user(change.login), change.role)

    def _do_RemoveTeamMember(self, change: diff.RemoveTeamMember) -> None:
        team = self._team(change.team)
        self._call(team.remove_membership, self._user(change.login))

    def _do_DeleteTeam(self, change: diff.DeleteTeam) -> None:
        self._call(self._team(change.name).delete)
        if self._teams is not None:
            del self._teams[change.name]

    # -- repositories --------------------------------------------------

    def _do_CreateRepository(self, change: diff.CreateRepository) -> None:
        wanted = change.repository
        if wanted.forked:
            upstream = self._call(self.gh.get_repo, wanted.forked)
            repo = self._call(
                upstream.create_fork, organization=self.org_name, name=wanted.name
            )
            edits: Dict[str, Any] = {}
            if (wanted.visibility == "private") != repo.private:
                edits["visibility"] = wanted.visibility
            if wanted.description and wanted.description != repo.description:
                edits["description"] = wanted.description
            if edits:
                self._call(repo.edit, **edits)
        else:
            repo = self._call(
                self.org.create_repo,
                wanted.name,
                description=wanted.description,
                visibility=wanted.visibility,
            )
        self._repos[wanted.name] = repo
        if wanted.topics:
            self._call(repo.replace_topics, sorted(wanted.topics))
        for team_name, access in sorted(wanted.teams.items()):
            self._call(self._team(team_name).update_team_repository, repo, access)
        for login, access in sorted(wanted.users.items()):
            self._call(repo.add_to_collaborators, login, access)

    def _do_UpdateRepository(self, change: diff.UpdateRepository) -> None:
        repo = self._repo(change.name)
        edits: Dict[str, Any] = {}
        for name, _, new in change.fields:
            if name == "topics":
                self._call(repo.replace_topics, list(new))
            else:
                edits[name] = new
        if edits:
            self._call(repo.edit, **edits)

    def _do_SetTeamAccess(self, change: diff.SetTeamAccess) -> None:
        team = self._team(change.team)
        self._call(
            team.update_team_repository, self._repo(change.repository), change.access
        )

    def _do_RemoveTeamAccess(self, change: diff.RemoveTeamAccess) -> None:
        team = self._team(change.team)
        self._call(team.remove_from_repos, self._repo(change.repository))

    def _do_SetUserAccess(self, change: diff.SetUserAccess) -> None:
        repo = self._repo(change.repository)
        self._call(repo.add_to_collaborators, change.login, change.access)

    def _do_RemoveUserAccess(self, change: diff.RemoveUserAccess) -> None:
        repo = self._repo(change.repository)
        self._call(repo.remove_from_collaborators, change.login)

    def _do_ArchiveRepository(self, change: diff.ArchiveRepository) -> None:
        self._call(self._repo(change.name).edit, archived=True)

    def _do_UnarchiveRepository(self, change: diff.UnarchiveRepository) -> None:
        self._call(self._repo(change.name).edit, archived=False)

    def _do_DeleteRepository(self, change: diff.DeleteRepository) -> None:
        self._call(self._repo(change.name).delete)
        self._repos.pop(change.name, None)

    # -- users ---------------------------------------------------------

    def _do_RemoveOrgMember(self, change: diff.RemoveOrgMember) -> None:
        self._call(self.org.remove_from_membership, self._user(change.login))

    def _do_RemoveOutsideCollaborator(
        self, change: diff.RemoveOutsideCollaborator
    ) -> None:
        self._call(self.org.remove_outside_collaborator, self._user(change.login))


def _retry_delay(exc: GithubException, attempt: int) -> float:
    """Seconds to wait after a rate limit error: server hint, else backoff."""
    headers = getattr(exc, "headers", None) or {}
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after) + 1
        except ValueError:
            pass
    reset = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
    if reset:
        try:
            return min(3600.0, max(1.0, float(reset) - time.time() + 1))
        except ValueError:
            pass
    return float(min(300, 30 * 2**attempt))


def _error_text(exc: Exception) -> str:
    if isinstance(exc, GithubException):
        data = exc.data
        message = data.get("message") if isinstance(data, dict) else data
        return f"HTTP {exc.status}: {message}"
    return str(exc)
