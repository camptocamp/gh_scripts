from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from typing import Dict, List, Tuple

from github import GithubException

from .utils import _build_github_client, setup_logging


@dataclass
class RepositoryUpdate:
    """Repository update instructions loaded from a CSV file.

    Attributes
    ----------
    department: str
        Value from the "C2C Department" column.
    add_teams: str
        Value from the "Teams to add" column.
    archive: bool
        True if the "Other actions" column contains "to archive".
    """

    department: str
    add_teams: str
    archive: bool


def read_repository_updates(csv_filename: str) -> Dict[str, RepositoryUpdate]:
    """Read a CSV file with repository update instructions.

    The CSV is expected to contain at least the following columns:

    - "name": repository name used as the dictionary key
    - "C2C Department": mapped to RepositoryUpdate.department
    - "Teams to add": mapped to RepositoryUpdate.add_teams
    - "Other actions": used to determine RepositoryUpdate.archive

    Returns a dictionary keyed by URL.
    """

    updates: Dict[str, RepositoryUpdate] = {}

    with open(csv_filename, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            if not row:
                continue
            if row["private"].strip().lower() == "false":
                continue

            name = row.get("name")
            if not name:
                raise ValueError(f"Missing 'name' column in row: {row}")

            department = row.get("C2C Department", "") or ""
            add_teams = row.get("Teams to add", "") or ""
            other_actions = row.get("Other actions", "") or ""

            archive = "to archive" in other_actions.lower()

            updates[name] = RepositoryUpdate(
                department=department,
                add_teams=add_teams,
                archive=archive,
            )

    return updates


def apply_repository_updates(
    organisation: str,
    updates_by_name: Dict[str, RepositoryUpdate],
    dry_run: bool = False,
) -> List[Tuple[str, Exception]]:
    """Apply a set of RepositoryUpdate instructions to repositories.

    Parameters
    ----------
    organisation: str
        GitHub organisation name.
    updates_by_name: Dict[str, RepositoryUpdate]
        Mapping of repository *names* to update instructions.
    dry_run: bool
        When True, log intended changes without modifying any repository.
    """

    logger = setup_logging()
    client = _build_github_client()
    org = client.get_organization(organisation)

    errors: List[Tuple[str, Exception]] = []

    for name, updates in updates_by_name.items():
        logger.info(
            "Updating repository '%s' (department=%s, add_teams=%s, archive=%s)",
            name,
            updates.department,
            updates.add_teams,
            updates.archive,
        )
        try:
            update_repository(org, name, updates, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error while updating repository '%s': %s", name, exc)
            errors.append((name, exc))

    return errors


def update_repository(
    org,
    name: str,
    updates: RepositoryUpdate,
    dry_run: bool = False,
) -> None:
    """Update a single repository according to RepositoryUpdate.

    - Ensure department topic is present on the repository.
    - Add requested teams with specified access levels.
    - Archive the repository if requested.
    """

    logger = setup_logging()

    department_topic_map = {
        "GS": "geospatial",
        "IS": "infrastructure",
        "BS": "business",
        "c2c": "camptocamp",
    }

    try:
        repo = org.get_repo(name)
    except GithubException as exc:  # type: ignore[attr-defined]
        # UnknownObjectException is raised when the repository is not found
        if getattr(exc, "status", None) == 404:
            logger.warning(
                "Repository '%s' not found in organisation '%s'",
                name,
                getattr(org, "login", "<unknown>"),
            )
            return
        logger.error(
            "Error fetching repository '%s' in organisation '%s': %s",
            name,
            getattr(org, "login", "<unknown>"),
            exc,
        )
        raise

    # Skip updates for already-archived repositories.
    if getattr(repo, "archived", False):
        logger.warning(
            "Repository '%s' in organisation '%s' is archived; skipping updates",
            name,
            getattr(org, "login", "<unknown>"),
        )
        return

    new_topic = []
    # 1. Ensure the department-related topic is set.
    department = (updates.department or "").strip()
    new_topic.append(department_topic_map.get(department))
    if "smartcamp" in updates.add_teams:  # Special case for SmartCamp team
        new_topic.append("smartcamp")
    current_topics = list(repo.get_topics() or [])
    topics_to_add = []
    for topic in new_topic:
        if not topic:
            continue
        if topic not in current_topics:
            topics_to_add.append(topic)
            current_topics.append(topic)

    if topics_to_add:
        if dry_run:
            logger.info(
                "Repository '%s': would add topics: %s",
                name,
                ", ".join(topics_to_add),
            )
        else:
            repo.replace_topics(current_topics)
            logger.info(
                "Repository '%s': added topics: %s",
                name,
                ", ".join(topics_to_add),
            )

    # 2. Add teams with the specified access level.
    add_teams_value = (updates.add_teams or "").strip()
    if add_teams_value:
        for pair in add_teams_value.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                continue

            team_name, access = pair.split(":", 1)
            team_name = team_name.strip()
            access = access.strip()
            if not team_name or not access:
                continue

            team = None
            # Try by slug first.
            try:
                team = org.get_team_by_slug(team_name)
            except Exception:
                # Fallback to lookup by display name.
                for t in org.get_teams():
                    if t.name == team_name:
                        team = t
                        break

            if not team:
                continue

            # Grant the team the requested permission level on the repo.
            if dry_run:
                logger.info(
                    "Repository '%s': would grant team '%s' access '%s'",
                    name,
                    team_name,
                    access,
                )
            else:
                team.set_repo_permission(repo, access)
                logger.info(
                    "Repository '%s': granted team '%s' access '%s'",
                    name,
                    team_name,
                    access,
                )

    # 3. Archive the repository if requested.
    if updates.archive and not repo.archived:
        if dry_run:
            logger.info("Repository '%s': would archive repository", name)
        else:
            repo.edit(archived=True)
            logger.info("Repository '%s': archived repository", name)


def main() -> None:
    """CLI entry point to apply repository updates from a CSV file.

    Expects arguments:
    - optional dry-run flag: -n or --dryrun
    - organisation name
    - input CSV filename
    """

    parser = argparse.ArgumentParser(
        description="Apply repository updates from a CSV file.",
    )
    parser.add_argument(
        "-n",
        "--dryrun",
        action="store_true",
        dest="dry_run",
        help="Log intended changes without modifying repositories.",
    )
    parser.add_argument("organisation", help="GitHub organisation name")
    parser.add_argument("input_csv", help="CSV file containing repository updates")
    args = parser.parse_args()

    organisation = args.organisation
    csv_filename = args.input_csv

    updates_by_name = read_repository_updates(csv_filename)
    errors = apply_repository_updates(
        organisation,
        updates_by_name,
        dry_run=args.dry_run,
    )

    if errors:
        logger = setup_logging()
        logger.error("%d repositories failed to update", len(errors))
        for repo_name, exc in errors:
            logger.error(" - %s: %s", repo_name, exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
