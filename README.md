# GitHub Organisation CSV Tools

This project provides small command-line tools to export and update GitHub organisation data using CSV files. It is built on top of [PyGithub](https://pygithub.readthedocs.io/).

## Installation

From the repository root, install in editable mode (recommended for development):

```bash
pip install -e .
```

This will install the console scripts:

- `github-repositories`
- `github-users`
- `github-repositories-update`

All tools authenticate with GitHub using the `GITHUB_TOKEN` environment variable (preferred). A local token file may also be used; see `src/c2c_gh_scripts/utils.py`.

## CLI Tools

### `github-repositories`

Export all repositories of an organisation to CSV.

```bash
github-repositories <organisation_name> <output_csv>
```

The CSV contains one row per repository, with columns such as:

- `name`, `description`, `private`, `fork`, `url`, `archived`
- `topics` (semicolon-separated)
- `teams` (semicolon-separated `team_name:permission` entries)

### `github-users`

Export organisation members and external collaborators to CSV.

```bash
github-users <organisation_name> <output_csv>
```

The CSV contains one row per user, with columns:

- `name`, `email`, `internal` (true for organisation members)
- `teams` (semicolon-separated team names)
- `repositories` (semicolon-separated repository names for external collaborators)

Internal members typically have teams populated; external collaborators may have both teams and repositories.

### `github-repositories-update`

Apply bulk updates to repositories from a CSV description.

```bash
github-repositories-update <organisation_name> <input_csv>
```

The input CSV is usually based on the export from `github-repositories`, with additional columns such as:

- `C2C Department` (used to add department topics)
- `Teams to add` (semicolon-separated team names)
- `Other actions` (e.g. values containing `to archive` to mark repositories for archiving)

The tool will add topics and teams and archive repositories according to the CSV content.

## Development Notes

- Code lives under `src/c2c_gh_scripts/` and uses type hints and dataclasses.
- CSV formats are part of the external contract; avoid breaking changes to columns or separators without coordination.
- There is no test suite yet; when adding tests, prefer `pytest` with a `tests/` directory and a simple `pytest` entry point.
