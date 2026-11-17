from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any, Iterable, List, Sequence

from github import GithubException

from .utils import _build_github_client, setup_logging


LOGGER_NAME = "github-repo-maintain"


class AbstractAction(ABC):
    """Base class for repository maintenance actions.

    An action encapsulates a single mutation that can be applied to a
    repository. Subclasses must implement :meth:`run` and are expected to be
    idempotent (running the same action multiple times should have no
    additional effect).

    Parameters
    ----------
    repository: Any
        PyGithub Repository object this action will operate on.
    """

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    @abstractmethod
    def run(self, dry_run: bool = False) -> None:
        """Execute the action against the target repository."""

    def describe(self) -> str:
        """Return a human-readable description of the action."""

        return f"{self.__class__.__name__} on {getattr(self.repository, 'full_name', '<unknown>')}"


class ActionAddTopic(AbstractAction):
    """Add a topic to a repository if it is not already present."""

    def __init__(self, repository: Any, topic: str) -> None:
        super().__init__(repository)
        self.topic = topic

    def describe(self) -> str:  # type: ignore[override]
        return f"Add topic '{self.topic}'"

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)
        topics = list(self.repository.get_topics() or [])
        if self.topic in topics:
            logger.info(
                "Repository '%s': topic '%s' already present; skipping",
                getattr(self.repository, "full_name", self.repository.name),
                self.topic,
            )
            return

        topics.append(self.topic)
        if dry_run:
            logger.info(
                "Repository '%s': would add topic '%s'",
                getattr(self.repository, "full_name", self.repository.name),
                self.topic,
            )
            return

        self.repository.replace_topics(topics)
        logger.info(
            "Repository '%s': added topic '%s'",
            getattr(self.repository, "full_name", self.repository.name),
            self.topic,
        )


class ActionRemoveTopic(AbstractAction):
    """Remove a topic from a repository if it is present."""

    def __init__(self, repository: Any, topic: str) -> None:
        super().__init__(repository)
        self.topic = topic

    def describe(self) -> str:  # type: ignore[override]
        return f"Remove topic '{self.topic}'"

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)
        topics = list(self.repository.get_topics() or [])
        if self.topic not in topics:
            logger.info(
                "Repository '%s': topic '%s' not present; skipping",
                getattr(self.repository, "full_name", self.repository.name),
                self.topic,
            )
            return

        topics = [t for t in topics if t != self.topic]
        if dry_run:
            logger.info(
                "Repository '%s': would remove topic '%s'",
                getattr(self.repository, "full_name", self.repository.name),
                self.topic,
            )
            return

        self.repository.replace_topics(topics)
        logger.info(
            "Repository '%s': removed topic '%s'",
            getattr(self.repository, "full_name", self.repository.name),
            self.topic,
        )


class ActionAddTeam(AbstractAction):
    """Grant a team the specified access level on a repository.

    Parameters
    ----------
    repository: Any
        Repository to update.
    team: Any
        PyGithub Team object.
    access: str
        Permission string such as "pull", "push", "maintain", or "admin".
    """

    def __init__(self, repository: Any, team: Any, access: str) -> None:
        super().__init__(repository)
        self.team = team
        self.access = access

    def describe(self) -> str:  # type: ignore[override]
        return f"Grant team '{getattr(self.team, 'slug', getattr(self.team, 'name', '<unknown>'))}' access '{self.access}'"

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)

        # Determine current permission, if any.
        permissions = self.team.get_repo_permission(self.repository)
        current_level = None
        if permissions is not None:
            for level in ("admin", "maintain", "push", "triage", "pull"):
                if getattr(permissions, level, False):
                    current_level = level
                    break

        if current_level == self.access:
            logger.info(
                "Repository '%s': team '%s' already has access '%s'; skipping",
                getattr(self.repository, "full_name", self.repository.name),
                getattr(self.team, "slug", getattr(self.team, "name", "<unknown>")),
                self.access,
            )
            return

        logger.info(
            "Repository '%s': setting team '%s' access to '%s' (was '%s')",
            getattr(self.repository, "full_name", self.repository.name),
            getattr(self.team, "slug", getattr(self.team, "name", "<unknown>")),
            self.access,
            current_level or "none",
        )
        if dry_run:
            return

        self.team.set_repo_permission(self.repository, self.access)


class ActionRemoveTeam(AbstractAction):
    """Remove a team's direct access to a repository if it exists."""

    def __init__(self, repository: Any, team: Any) -> None:
        super().__init__(repository)
        self.team = team

    def describe(self) -> str:  # type: ignore[override]
        return f"Remove team '{getattr(self.team, 'slug', getattr(self.team, 'name', '<unknown>'))}' access"

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)

        if not self.team.has_in_repos(self.repository):
            logger.info(
                "Repository '%s': team '%s' has no direct access; skipping",
                getattr(self.repository, "full_name", self.repository.name),
                getattr(self.team, "slug", getattr(self.team, "name", "<unknown>")),
            )
            return

        logger.info(
            "Repository '%s': removing team '%s' access",
            getattr(self.repository, "full_name", self.repository.name),
            getattr(self.team, "slug", getattr(self.team, "name", "<unknown>")),
        )
        if dry_run:
            return

        self.team.remove_from_repos(self.repository)


class ActionRemoveUser(AbstractAction):
    """Remove a user's direct access to a repository if present.

    This only affects direct collaborator access and does not change
    permissions granted through teams.
    """

    def __init__(self, repository: Any, user: Any) -> None:
        super().__init__(repository)
        self.user = user

    def describe(self) -> str:  # type: ignore[override]
        identifier = getattr(self.user, "login", None) or str(self.user)
        return f"Remove direct user access for '{identifier}'"

    def run(self, dry_run: bool = False) -> None:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)

        if not self.repository.has_in_collaborators(self.user):
            logger.info(
                "Repository '%s': user '%s' has no direct access; skipping",
                getattr(self.repository, "full_name", self.repository.name),
                getattr(self.user, "login", None) or str(self.user),
            )
            return

        logger.info(
            "Repository '%s': removing direct access for user '%s'",
            getattr(self.repository, "full_name", self.repository.name),
            getattr(self.user, "login", None) or str(self.user),
        )
        if dry_run:
            return

        self.repository.remove_from_collaborators(self.user)


class Rule(ABC):
    """Base class for rules that produce actions for a repository."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def evaluate(self, repository: Any) -> List[AbstractAction]:
        """Return the list of actions this rule proposes for the repository."""


def _has_admin_access(repository: Any, team_identifier: str) -> bool:
    """Return True if a team has admin access on the repository.

    The check matches on either team slug or display name.
    """

    for team in repository.get_teams():
        slug = getattr(team, "slug", None)
        name = getattr(team, "name", None)
        if team_identifier not in {slug, name}:
            continue

        permission = getattr(team, "permission", None)
        if permission is None and hasattr(team, "permissions"):
            perms = getattr(team, "permissions") or {}
            for level in ("admin", "maintain", "push", "triage", "pull"):
                if perms.get(level):
                    permission = level
                    break

        if permission == "admin":
            return True

    return False


class RuleSmartcampTopic(Rule):
    """Add the "smartcamp" topic when bs-team-smartcamp has admin access."""

    def __init__(self) -> None:
        super().__init__(name="RuleSmartcampTopic")

    def evaluate(self, repository: Any) -> List[AbstractAction]:  # type: ignore[override]
        if not _has_admin_access(repository, "bs-team-smartcamp"):
            return []

        return [ActionAddTopic(repository, "smartcamp")]


class RuleBusinessTopic(Rule):
    """Add the "business" topic when business-division has admin access."""

    def __init__(self) -> None:
        super().__init__(name="RuleBusinessTopic")

    def evaluate(self, repository: Any) -> List[AbstractAction]:  # type: ignore[override]
        if not _has_admin_access(repository, "business-division"):
            return []

        return [ActionAddTopic(repository, "business")]


def _parse_odoo_version(raw_version: str) -> tuple[int, int, int, int, int] | None:
    """Parse an odoo/VERSION string in the form "a.b.c.d.e".

    Returns None when the version does not match the expected format.
    """

    parts = [p.strip() for p in raw_version.strip().split(".") if p.strip()]
    if len(parts) != 5:
        return None

    try:
        values = tuple(int(p) for p in parts)
    except ValueError:
        return None

    return values  # type: ignore[return-value]


class RuleBusinessOdooVersionTopic(Rule):
    """Maintain odoo-related topics based on odoo/VERSION for business repos.

    Logic
    -----
    - If the repository does not have the "business" topic, do nothing.
    - If the file "odoo/VERSION" does not exist on the default branch or is not
      in the expected format "a.b.c.d.e", do nothing.
    - Otherwise:
      - Ensure topics "odoo-project" and "odoo-<a>" are present.
      - For any existing topic "odoo-<nnn>" where <nnn> != <a>, remove it.
    """

    def __init__(self) -> None:
        super().__init__(name="RuleBusinessOdooVersionTopic")

    def evaluate(self, repository: Any) -> List[AbstractAction]:  # type: ignore[override]
        logger = setup_logging(LOGGER_NAME)
        topics = list(repository.get_topics() or [])

        if "business" not in topics:
            return []

        default_branch = getattr(repository, "default_branch", "main")
        try:
            content_file = repository.get_contents("odoo/VERSION", ref=default_branch)
        except GithubException as exc:  # type: ignore[attr-defined]
            if getattr(exc, "status", None) == 404:
                logger.info(
                    "Repository '%s': no odoo/VERSION file on branch '%s'; skipping odoo topics",
                    getattr(repository, "full_name", repository.name),
                    default_branch,
                )
                return []
            logger.warning(
                "Repository '%s': error fetching odoo/VERSION: %s",
                getattr(repository, "full_name", repository.name),
                exc,
            )
            return []

        raw_version_bytes = getattr(content_file, "decoded_content", None)
        if raw_version_bytes is None:
            logger.warning(
                "Repository '%s': odoo/VERSION has no decoded_content; skipping",
                getattr(repository, "full_name", repository.name),
            )
            return []

        raw_version = raw_version_bytes.decode("utf-8").strip()
        parsed = _parse_odoo_version(raw_version)
        if parsed is None:
            logger.warning(
                "Repository '%s': unexpected odoo/VERSION format '%s'; expected a.b.c.d.e",
                getattr(repository, "full_name", repository.name),
                raw_version,
            )
            return []

        major = parsed[0]
        actions: List[AbstractAction] = []

        # Ensure required topics are present.
        actions.append(ActionAddTopic(repository, "odoo-project"))
        actions.append(ActionAddTopic(repository, f"odoo-{major}"))

        # Remove outdated odoo-<nnn> topics.
        for topic in topics:
            if not topic.startswith("odoo-"):
                continue
            suffix = topic[len("odoo-") :]
            if not suffix.isdigit():
                continue
            if int(suffix) != major:
                actions.append(ActionRemoveTopic(repository, topic))

        return actions


def build_rules() -> List[Rule]:
    """Construct the list of rules applied to each repository."""

    return [
        RuleSmartcampTopic(),
        RuleBusinessTopic(),
        RuleBusinessOdooVersionTopic(),
    ]


def _evaluate_rules(repository: Any, rules: Sequence[Rule]) -> List[AbstractAction]:
    """Evaluate all rules for a repository and collect proposed actions."""

    actions: List[AbstractAction] = []
    for rule in rules:
        try:
            rule_actions = rule.evaluate(repository)
        except Exception as exc:  # noqa: BLE001
            logger = setup_logging(LOGGER_NAME)
            logger.error(
                "Error while evaluating rule '%s' for repository '%s': %s",
                rule.name,
                getattr(
                    repository, "full_name", getattr(repository, "name", "<unknown>")
                ),
                exc,
            )
            continue

        actions.extend(rule_actions or [])

    return actions


def _run_actions(
    repository: Any,
    actions: Iterable[AbstractAction],
    dry_run: bool = False,
) -> List[Exception]:
    """Execute all actions for a repository, collecting any failures."""

    logger = setup_logging(LOGGER_NAME)
    errors: List[Exception] = []

    for action in actions:
        try:
            logger.info(
                "Repository '%s': running action: %s",
                getattr(
                    repository, "full_name", getattr(repository, "name", "<unknown>")
                ),
                action.describe(),
            )
            action.run(dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Repository '%s': action '%s' failed: %s",
                getattr(
                    repository, "full_name", getattr(repository, "name", "<unknown>")
                ),
                action.describe(),
                exc,
            )
            errors.append(exc)

    return errors


def run_for_organisation(
    organisation: str,
    dry_run: bool = False,
) -> List[tuple[str, Exception]]:
    """Run maintenance rules for all repositories in an organisation.

    Parameters
    ----------
    organisation: str
        GitHub organisation name.
    dry_run: bool
        When True, only log actions without changing repositories.

    Returns
    -------
    List[Tuple[str, Exception]]
        List of (repository_full_name, exception) tuples for any failed
        actions.
    """

    logger = setup_logging(LOGGER_NAME)
    client = _build_github_client()
    org = client.get_organization(organisation)

    rules = build_rules()
    logger.info(
        "Running %d rules on repositories of organisation '%s'",
        len(rules),
        getattr(org, "login", organisation),
    )

    errors: List[tuple[str, Exception]] = []

    for repo in org.get_repos(type="all"):
        full_name = getattr(repo, "full_name", repo.name)
        if getattr(repo, "archived", False):
            logger.info("Repository '%s' is archived; skipping", full_name)
            continue

        logger.info("Processing repository '%s'", full_name)
        actions = _evaluate_rules(repo, rules)
        if not actions:
            continue

        repo_errors = _run_actions(repo, actions, dry_run=dry_run)
        for exc in repo_errors:
            errors.append((full_name, exc))

    if errors:
        logger.error("%d repositories had at least one failed action", len(errors))

    return errors


def main() -> None:
    """CLI entry point for github-repo-maintain.

    Expects arguments:
    - optional dry-run flag: -n or --dryrun
    - organisation name
    """

    parser = argparse.ArgumentParser(
        description="Run repository maintenance rules for an organisation.",
    )
    parser.add_argument(
        "-n",
        "--dryrun",
        action="store_true",
        dest="dry_run",
        help="List actions without changing repositories.",
    )
    parser.add_argument("organisation", help="GitHub organisation name")
    args = parser.parse_args()

    errors = run_for_organisation(args.organisation, dry_run=args.dry_run)

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
