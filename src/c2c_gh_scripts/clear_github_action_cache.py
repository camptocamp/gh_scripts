from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, List

from github import GithubException

from .utils import _build_github_client, setup_logging

LOGGER_NAME = "clear-github-action-cache"


def _parse_since(value: str) -> datetime:
    """Parse an ISO 8601 datetime, assuming UTC when no timezone is given."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_created_at(value: str) -> datetime:
    """Parse a GitHub API timestamp (e.g. '2026-01-01T00:00:00Z')."""

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_caches(repository: Any) -> List[dict]:
    """Return all Actions caches for a repository via the raw REST API.

    PyGithub has no built-in support for the Actions Cache endpoints, so this
    uses the repository's internal requester to call them directly.
    """

    caches: List[dict] = []
    page = 1
    while True:
        _, data = repository._requester.requestJsonAndCheck(
            "GET",
            f"{repository.url}/actions/caches",
            parameters={"per_page": 100, "page": page},
        )
        page_caches = data.get("actions_caches", [])
        if not page_caches:
            break
        caches.extend(page_caches)
        page += 1

    return caches


def delete_cache(repository: Any, cache_id: int) -> None:
    """Delete a single Actions cache by id via the raw REST API."""

    repository._requester.requestJsonAndCheck(
        "DELETE",
        f"{repository.url}/actions/caches/{cache_id}",
    )


def clear_caches(
    organisation: str, repo_name: str, since: datetime, dry_run: bool = False
) -> int:
    """Delete Actions caches created on/after `since` for a repository.

    Returns
    -------
    int
        Number of caches deleted (or that would be deleted in dry-run mode).
    """

    logger = setup_logging(LOGGER_NAME)
    client = _build_github_client()
    repository = client.get_repo(f"{organisation}/{repo_name}")

    caches = list_caches(repository)
    matching = [c for c in caches if _parse_created_at(c["created_at"]) >= since]
    logger.info(
        "Repository '%s': %d cache(s) match 'created since %s' out of %d total",
        repository.full_name,
        len(matching),
        since.isoformat(),
        len(caches),
    )

    deleted = 0
    for cache in matching:
        if dry_run:
            logger.info(
                "Repository '%s': would delete cache '%s' (id=%s, created_at=%s)",
                repository.full_name,
                cache.get("key"),
                cache.get("id"),
                cache.get("created_at"),
            )
            deleted += 1
            continue

        try:
            delete_cache(repository, cache["id"])
            logger.info(
                "Repository '%s': deleted cache '%s' (id=%s, created_at=%s)",
                repository.full_name,
                cache.get("key"),
                cache.get("id"),
                cache.get("created_at"),
            )
            deleted += 1
        except GithubException as exc:
            logger.error(
                "Repository '%s': failed to delete cache '%s' (id=%s): %s",
                repository.full_name,
                cache.get("key"),
                cache.get("id"),
                exc,
            )

    return deleted


def main() -> None:
    """CLI entry point for clear-github-action-cache."""

    parser = argparse.ArgumentParser(
        description="Delete GitHub Actions caches created since a given datetime for a repository.",
    )
    parser.add_argument("--org", required=True, help="GitHub organisation name")
    parser.add_argument(
        "--repo", required=True, help="Repository name (without organisation prefix)"
    )
    parser.add_argument(
        "--since",
        required=True,
        type=_parse_since,
        help="ISO 8601 datetime; caches created on/after this time are deleted (naive values assumed UTC)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching caches without deleting them.",
    )
    args = parser.parse_args()

    logger = setup_logging(LOGGER_NAME)
    try:
        clear_caches(args.org, args.repo, args.since, dry_run=args.dry_run)
    except GithubException as exc:
        logger.error(
            "Failed to access repository '%s/%s': %s", args.org, args.repo, exc
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
