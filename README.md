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

### `github-org-manager` (`gom`)

Manage the teams and repositories of an organisation from YAML files kept in a
separate repository. Each file holds one or more records (`type: team` or
`type: repository`, multi-document files separated by `---`), found recursively
under the given directory.

```bash
gom check <path_to_config>
gom generate --org <org> [-r <repo>]... [-t <team>]... [--report <file>] <path_to_config>
gom apply [-n|--dry-run] [--prune-repo] [--prune-team] [--prune-user] --org <org> <path_to_config>
```

- `check` validates the configuration and exits with status 1 on errors.
- `generate` writes `teams/<name>.yaml` and `repos/<name>.yaml` from the current
  state of the organisation, overwriting existing files. It then prints a report
  of empty teams, users without a team (with the repositories they can access),
  repositories without teams and repositories without an admin team; `--report`
  also saves it to a file.
- `apply` makes the organisation match the configuration. Repositories which are
  not configured are logged as warnings (with the file to add) unless
  `--prune-repo` is given; likewise teams with `--prune-team`. `--prune-user`
  removes members who are in no configured team (never organisation owners) and
  outside collaborators not listed in any repository. `-n` only lists the
  changes. When more seats are needed than the organisation has, the number of
  missing seats is logged as a warning and the extra users are not invited.
  The exit status is 1 if any error occurred or any change failed.

## Development Notes

- Code lives under `src/c2c_gh_scripts/` and uses type hints and dataclasses.
- CSV formats are part of the external contract; avoid breaking changes to columns or separators without coordination.
- There is no test suite yet; when adding tests, prefer `pytest` with a `tests/` directory and a simple `pytest` entry point.
