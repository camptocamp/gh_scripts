# Project Guidelines

## Code Style
- Python 3.9+ with type hints throughout; follow patterns in src/c2c_gh_scripts/*.py.
- Use dataclasses for structured data models (for example RepositoryInfo, UserInfo, RepositoryUpdate).
- Keep using Google-style docstrings with clear Parameters/Returns sections.
- Prefer the standard library plus PyGithub; avoid introducing new dependencies unless there is strong justification.

## Architecture
- Single package c2c_gh_scripts under src/ providing three CLI tools:
  - github-repositories: export GitHub organisation repositories to CSV.
  - github-users: export organisation users (internal vs external collaborators) to CSV.
  - github-repositories-update: apply bulk repository updates from a CSV description.
- Shared concerns (GitHub client construction, logging) live in src/c2c_gh_scripts/utils.py and should be reused rather than reimplemented.
- Each CLI has a small, focused main() with thin argument parsing and the work done in separate functions; keep new functionality similarly structured.

## Build and Test
- Install in editable mode during development: `pip install -e .` from the workspace root (pyproject.toml uses setuptools backend and depends on PyGithub).
- After installation, the main entry points are available as console scripts:
  - github-repositories
  - github-users
  - github-repositories-update
- Each CLI currently expects exactly two arguments: `<organisation_name> <csv_filename>`.
- There is no established test suite yet. When adding tests, prefer pytest with a tests/ directory and a simple `pytest` command as the default test entry.
- In the absence of automated tests, prefer small, reviewable changes and avoid large refactors in a single step.

## Conventions
- CSV schemas are part of the external contract; preserve existing columns and their meanings when modifying code that reads or writes CSV.
- Lists in CSV fields (topics, teams, repositories) are semicolon-separated; keep using this convention unless the format is intentionally versioned.
- Team permissions are encoded as `team_name:permission_level`; do not change this format without updating all related readers/writers.
- For user exports, internal members primarily have teams populated; external collaborators may have both teams and repositories populated. Do not silently change this behaviour.
- Reuse the existing dataclasses fields and naming patterns when extending models.
 - Always run `pre-commit run --all-files` (ruff lint + format) on any files you create or modify before committing.

## Environment and Pitfalls
- GitHub authentication is constructed via utils._build_github_client(). Prefer the GITHUB_TOKEN environment variable; the hardcoded fallback path `/home/afayolle/.github_token2` is user-specific and should not be relied on in new code.
- Keep logging consistent by using utils.setup_logging() instead of ad-hoc print statements.
- Be mindful that there is no CI configuration or linting tooling configured yet; when introducing such tooling, keep it lightweight and aligned with the existing style.
- Maintain backward-compatible CLI behaviour where feasible (arguments, exit codes, and CSV formats), as these tools may be used in scripts or automation.
