"""github-org-manager (gom): manage GitHub teams and repositories from YAML files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Tuple

import click

from .org_manager.config import load_config, write_config
from .org_manager.diff import Plan, compute_changes
from .org_manager.models import LEVEL_ERROR, Issue, OrgConfig
from .org_manager.state import load_github_state, load_org_state
from .org_manager.validation import validate
from .utils import _build_github_client, setup_logging

LOGGER_NAME = "github-org-manager"


def check_configuration(path: Path) -> List[Issue]:
    """Load and validate the configuration under ``path``.

    Parameters
    ----------
    path: Path
        Directory holding the YAML definition files.

    Returns
    -------
    list[Issue]
        Loading problems followed by validation problems.
    """
    config, issues = load_config(path)
    issues.extend(validate(config))
    return issues


@click.group()
def main() -> None:
    """Manage the teams and repositories of a GitHub organisation."""


def log_issues(logger: Any, issues: List[Issue]) -> int:
    """Log issues at their own level and return the number of errors."""
    errors = 0
    for issue in issues:
        text = f"{issue.source}: {issue.message}" if issue.source else issue.message
        if issue.level == LEVEL_ERROR:
            errors += 1
            logger.error("%s", text)
        else:
            logger.warning("%s", text)
    return errors


def generate_configuration(
    gh: Any,
    org_name: str,
    config_path: Path,
    repo_names: Tuple[str, ...] = (),
    team_names: Tuple[str, ...] = (),
) -> Tuple[int, List[Issue]]:
    """Export the state of an organisation as definition files.

    Parameters
    ----------
    gh: github.Github
        Authenticated GitHub client.
    org_name: str
        Name of the organisation.
    config_path: Path
        Directory where the files are written (created if needed).
    repo_names: tuple[str, ...]
        Restrict the export to these repositories (all when empty).
    team_names: tuple[str, ...]
        Restrict the export to these teams (all when empty).

    Returns
    -------
    tuple[int, list[Issue]]
        Number of files written, and the problems found. The rules are only
        checked on complete exports, since a partial one lacks the records
        it refers to.
    """
    config, issues = load_github_state(gh, org_name, repo_names, team_names)
    written = write_config(config, config_path)
    if not repo_names and not team_names:
        issues.extend(validate(config))
    return len(written), issues


class InvalidConfiguration(Exception):
    """The configuration does not pass the checks."""

    def __init__(self, issues: List[Issue]) -> None:
        super().__init__("invalid configuration")
        self.issues = issues


def load_valid_config(config_path: Path) -> Tuple[OrgConfig, List[Issue]]:
    """Load the configuration, which must pass the checks.

    Returns
    -------
    tuple[OrgConfig, list[Issue]]
        The configuration and its warnings.

    Raises
    ------
    InvalidConfiguration
        If the configuration has errors.
    """
    config, issues = load_config(config_path)
    issues.extend(validate(config))
    if any(i.level == LEVEL_ERROR for i in issues):
        raise InvalidConfiguration(issues)
    return config, issues


def plan_changes(
    gh: Any,
    org_name: str,
    config: OrgConfig,
    prune_teams: bool = False,
    prune_repos: bool = False,
    prune_users: bool = False,
) -> Plan:
    """Compare the configuration with the organisation.

    Parameters
    ----------
    gh: github.Github
        Authenticated GitHub client.
    org_name: str
        Name of the organisation.
    config: OrgConfig
        The validated target configuration.
    prune_teams, prune_repos, prune_users: bool
        Allow deleting teams, repositories, and removing users.

    Returns
    -------
    Plan
        The changes to apply and the problems found.
    """
    state, state_issues = load_org_state(gh, org_name)
    plan = compute_changes(config, state, prune_teams, prune_repos, prune_users)
    plan.issues = state_issues + plan.issues
    return plan


@main.command("check")
@click.argument(
    "config_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def check_command(config_path: Path) -> None:
    """Check the configuration found in CONFIG_PATH.

    Exits with status 1 if any error is found; warnings do not fail the check.
    """
    logger = setup_logging(LOGGER_NAME)
    issues = check_configuration(config_path)
    errors = log_issues(logger, issues)
    if errors:
        logger.error("configuration is invalid: %d error(s)", errors)
        sys.exit(1)
    logger.info("configuration is valid")


@main.command("generate")
@click.option("--org", "org_name", required=True, help="Organisation name.")
@click.option(
    "-r",
    "--repo",
    "repo_names",
    multiple=True,
    help="Repository to export (repeatable). All repositories by default.",
)
@click.option(
    "-t",
    "--team",
    "team_names",
    multiple=True,
    help="Team to export (repeatable). All teams by default.",
)
@click.argument("config_path", type=click.Path(file_okay=False, path_type=Path))
def generate_command(
    org_name: str,
    repo_names: Tuple[str, ...],
    team_names: Tuple[str, ...],
    config_path: Path,
) -> None:
    """Write the current state of the organisation into CONFIG_PATH.

    Existing definition files are overwritten.
    """
    logger = setup_logging(LOGGER_NAME)
    count, issues = generate_configuration(
        _build_github_client(), org_name, config_path, repo_names, team_names
    )
    log_issues(logger, issues)
    logger.info("wrote %d file(s) to %s", count, config_path)


@main.command("apply")
@click.option(
    "-n",
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="List the changes without applying them.",
)
@click.option(
    "--prune-repo", is_flag=True, help="Delete repositories missing from the config."
)
@click.option(
    "--prune-team", is_flag=True, help="Delete teams missing from the config."
)
@click.option(
    "--prune-user",
    is_flag=True,
    help="Remove members in no configured team, and unlisted outside collaborators.",
)
@click.option("--org", "org_name", required=True, help="Organisation name.")
@click.argument(
    "config_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def apply_command(
    dry_run: bool,
    prune_repo: bool,
    prune_team: bool,
    prune_user: bool,
    org_name: str,
    config_path: Path,
) -> None:
    """Apply the configuration found in CONFIG_PATH to the organisation."""
    if not dry_run:
        raise click.ClickException("real runs are not implemented yet, use --dry-run")
    logger = setup_logging(LOGGER_NAME)
    try:
        config, issues = load_valid_config(config_path)
    except InvalidConfiguration as exc:
        log_issues(logger, exc.issues)
        logger.error("configuration is invalid, nothing done")
        sys.exit(1)
    plan = plan_changes(
        _build_github_client(),
        org_name,
        config,
        prune_teams=prune_team,
        prune_repos=prune_repo,
        prune_users=prune_user,
    )
    errors = log_issues(logger, issues + plan.issues)
    for change in plan.changes:
        logger.info("[dry-run] %s", change.describe())
    logger.info("%d change(s) to apply", len(plan.changes))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
