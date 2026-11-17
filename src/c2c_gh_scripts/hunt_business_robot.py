"""Hunt for .github/setup.js files across branches and pull requests of an organisation.

Scans every repository (public and private) of a GitHub organisation, looking
for a ``setup.js`` file located in the ``.github/`` directory at the root of
the repository, in the tree of each branch, and among the files changed by
each pull request. Produces a Markdown report with one section per affected
repository, linking to the matching branches and pull requests on GitHub.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import List

from github import GithubException

from .utils import _build_github_client, setup_logging

TARGET_PATH = ".github/setup.js"
BUSINESS_TEAM_SLUG = "business-division"

logger = setup_logging("hunt-business-robot")


@dataclass
class BranchMatch:
    """A branch whose tree contains one of the target files."""

    branch_name: str
    files: List[str]
    url: str


@dataclass
class PullRequestMatch:
    """A pull request that touches one of the target files."""

    number: int
    title: str
    files: List[str]
    url: str


@dataclass
class RepositoryFindings:
    """Aggregated findings for a single repository."""

    name: str
    branches: List[BranchMatch] = field(default_factory=list)
    pull_requests: List[PullRequestMatch] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.branches or self.pull_requests)


def _matching_paths(paths: List[str]) -> List[str]:
    return [path for path in paths if path == TARGET_PATH]


def _tree_target_files(repo, sha: str) -> List[str]:
    """Return the paths of target files present in the git tree at ``sha``."""

    try:
        tree = repo.get_git_tree(sha, recursive=True)
    except GithubException as exc:
        logger.warning("Failed to get tree for %s@%s: %s", repo.full_name, sha, exc)
        return []

    if tree.truncated:
        logger.warning(
            "Tree truncated for %s@%s; results may be incomplete", repo.full_name, sha
        )

    return _matching_paths([entry.path for entry in tree.tree if entry.type == "blob"])


def _check_branches(repo) -> List[BranchMatch]:
    results: List[BranchMatch] = []
    for branch in repo.get_branches():
        matches = _tree_target_files(repo, branch.commit.sha)
        if matches:
            url = f"{repo.html_url}/tree/{branch.name}"
            results.append(BranchMatch(branch_name=branch.name, files=matches, url=url))
    return results


def _check_pull_requests(repo) -> List[PullRequestMatch]:
    results: List[PullRequestMatch] = []
    for pull_request in repo.get_pulls(state="all"):
        try:
            filenames = [pr_file.filename for pr_file in pull_request.get_files()]
        except GithubException as exc:
            logger.warning(
                "Failed to get files for PR #%s in %s: %s",
                pull_request.number,
                repo.full_name,
                exc,
            )
            continue

        matches = _matching_paths(filenames)
        if matches:
            results.append(
                PullRequestMatch(
                    number=pull_request.number,
                    title=pull_request.title,
                    files=matches,
                    url=pull_request.html_url,
                )
            )
    return results


def _ordered_repos(org) -> List:
    """Return org repositories ordered so that repositories accessible by the
    ``business-division`` team come first (private before public), followed by
    the repositories the team cannot access.
    """

    all_repos = list(org.get_repos(type="all"))

    team_repo_ids = set()
    try:
        team = org.get_team_by_slug(BUSINESS_TEAM_SLUG)
    except GithubException as exc:
        logger.warning(
            "Failed to find team '%s' in %s: %s", BUSINESS_TEAM_SLUG, org.login, exc
        )
        team = None

    if team is not None:
        try:
            team_repo_ids = {repo.id for repo in team.get_repos()}
        except GithubException as exc:
            logger.warning(
                "Failed to list repositories for team '%s': %s", BUSINESS_TEAM_SLUG, exc
            )

    team_private = [
        repo for repo in all_repos if repo.id in team_repo_ids and repo.private
    ]
    team_public = [
        repo for repo in all_repos if repo.id in team_repo_ids and not repo.private
    ]
    others = [repo for repo in all_repos if repo.id not in team_repo_ids]

    return team_private + team_public + others


def hunt(organisation: str) -> List[RepositoryFindings]:
    """Scan all repositories of ``organisation`` for the target files."""

    github_client = _build_github_client()
    org = github_client.get_organization(organisation)

    findings: List[RepositoryFindings] = []
    for repo in _ordered_repos(org):
        logger.info("Scanning repository %s", repo.full_name)
        repo_findings = RepositoryFindings(name=repo.full_name)
        repo_findings.branches = _check_branches(repo)
        repo_findings.pull_requests = _check_pull_requests(repo)
        if repo_findings.has_findings:
            logger.info(
                "Found %d branch(es) and %d pull request(s) in %s",
                len(repo_findings.branches),
                len(repo_findings.pull_requests),
                repo.full_name,
            )
            findings.append(repo_findings)
    return findings


def write_report(findings: List[RepositoryFindings], output_filename: str) -> None:
    """Write a Markdown report with one section per affected repository."""

    with open(output_filename, "w", encoding="utf-8") as report_file:
        report_file.write("# .github/setup.js hunt report\n\n")

        if not findings:
            report_file.write("No matches found.\n")
            return

        for repo_findings in findings:
            report_file.write(f"## {repo_findings.name}\n\n")

            if repo_findings.branches:
                report_file.write("### Branches\n\n")
                for branch in repo_findings.branches:
                    files_str = ", ".join(branch.files)
                    report_file.write(
                        f"- [{branch.branch_name}]({branch.url}): {files_str}\n"
                    )
                report_file.write("\n")

            if repo_findings.pull_requests:
                report_file.write("### Pull requests\n\n")
                for pull_request in repo_findings.pull_requests:
                    files_str = ", ".join(pull_request.files)
                    report_file.write(
                        f"- [#{pull_request.number} {pull_request.title}]"
                        f"({pull_request.url}): {files_str}\n"
                    )
                report_file.write("\n")


def main() -> None:
    """Entry point for command-line usage."""

    parser = argparse.ArgumentParser(
        description="Hunt for .github/setup.js files across an organisation's repositories."
    )
    parser.add_argument(
        "organisation", help="GitHub organisation login, e.g. camptocamp"
    )
    parser.add_argument(
        "output_markdown", help="Path to the Markdown report to generate"
    )
    args = parser.parse_args()

    findings = hunt(args.organisation)
    write_report(findings, args.output_markdown)
    logger.info("Report written to %s", args.output_markdown)


if __name__ == "__main__":
    main()
