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
- `github-repo-maintain`

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

### `github-repo-maintain`

Run the built-in repository maintenance rules for all non-archived repositories
in an organisation.

```bash
github-repo-maintain [--dryrun] <organisation_name>
```

The rules add the `smartcamp` topic when the `bs-team-smartcamp` team has admin
access, add the `business` topic when the `business-division` team has admin
access, and maintain Odoo topics for business repositories based on their
`odoo/VERSION` file. Odoo topic maintenance adds `odoo-project` and the matching
`odoo-<major_version>` topic, and removes outdated numeric `odoo-*` topics.

Use `--dryrun` (or `-n`) to log the actions that would be taken without changing
repositories.

## Development Notes

- Code lives under `src/c2c_gh_scripts/` and uses type hints and dataclasses.
- CSV formats are part of the external contract; avoid breaking changes to columns or separators without coordination.
- There is no test suite yet; when adding tests, prefer `pytest` with a `tests/` directory and a simple `pytest` entry point.
