"""github-org-manager (gom): manage GitHub teams and repositories from YAML files."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import click

from .org_manager.config import load_config
from .org_manager.models import LEVEL_ERROR, Issue
from .org_manager.validation import validate
from .utils import setup_logging

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
    errors = 0
    for issue in issues:
        if issue.level == LEVEL_ERROR:
            errors += 1
            logger.error(
                "%s%s", f"{issue.source}: " if issue.source else "", issue.message
            )
        else:
            logger.warning(
                "%s%s", f"{issue.source}: " if issue.source else "", issue.message
            )
    if errors:
        logger.error("configuration is invalid: %d error(s)", errors)
        sys.exit(1)
    logger.info("configuration is valid")


if __name__ == "__main__":
    main()
