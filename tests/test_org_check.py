from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest
from click.testing import CliRunner

from c2c_gh_scripts.github_org_manager import check_configuration, main
from c2c_gh_scripts.org_manager.config import load_config
from c2c_gh_scripts.org_manager.models import LEVEL_ERROR, LEVEL_WARNING
from c2c_gh_scripts.org_manager.validation import validate

VALID_TEAM = """\
type: team
name: devs
maintainers: [alice]
members: [bob]
"""

VALID_REPO = """\
type: repository
name: tool
visibility: private
description: A tool
teams:
  devs: admin
"""


def write(root: Path, files: Dict[str, str]) -> Path:
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def messages(path: Path, level: str) -> list:
    return [i.message for i in check_configuration(path) if i.level == level]


def test_valid_configuration(tmp_path):
    write(tmp_path, {"teams/devs.yaml": VALID_TEAM, "repos/tool.yml": VALID_REPO})
    assert check_configuration(tmp_path) == []


def test_loading_defaults_and_multi_document(tmp_path):
    write(
        tmp_path,
        {
            "all.yaml": VALID_TEAM + "---\n" + VALID_REPO,
            "nested/deeper/other.txt": "ignored: [",
        },
    )
    config, issues = load_config(tmp_path)
    assert issues == []
    team = config.teams[0]
    assert (team.parent, team.members) == ("", ["bob"])
    repo = config.repositories[0]
    assert (repo.topics, repo.users, repo.archived, repo.forked) == ([], {}, False, "")


@pytest.mark.parametrize(
    "content, expected",
    [
        ("name: x\n", "unknown or missing record type"),
        ("type: widget\n", "unknown or missing record type"),
        ("- a\n- b\n", "must be a mapping"),
        ("type: team\nname: [\n", "invalid YAML"),
        ("type: team\nmaintainers: [a]\n", "'name' is required"),
        ("type: team\nname: t\nmaintainers: a\n", "list of strings"),
        ("type: team\nname: t\nmaintainers: [a]\nowner: x\n", "unknown field 'owner'"),
        ("type: repository\nname: r\narchived: yes please\n", "must be a boolean"),
        ("type: repository\nname: r\nteams: [a]\n", "mapping of strings"),
    ],
)
def test_loading_errors(tmp_path, content, expected):
    write(tmp_path, {"bad.yaml": content})
    _, issues = load_config(tmp_path)
    assert any(expected in i.message and i.level == LEVEL_ERROR for i in issues)


def test_team_rules(tmp_path):
    write(
        tmp_path,
        {
            "a.yaml": "type: team\nname: a\nmaintainers: []\n",
            "b.yaml": "type: team\nname: b\nmaintainers: [x]\nmembers: [x]\nparent: nope\n",
            "c.yaml": "type: team\nname: c\nmaintainers: [x]\n",
            "c2.yaml": "type: team\nname: c\nmaintainers: [x]\n",
        },
    )
    errors = messages(tmp_path, LEVEL_ERROR)
    assert any("at least one maintainer" in m for m in errors)
    assert any("both maintainer and member" in m for m in errors)
    assert any("parent team 'nope' is not defined" in m for m in errors)
    assert sum("defined more than once" in m for m in errors) == 2


def test_team_parent_cycle(tmp_path):
    write(
        tmp_path,
        {
            "a.yaml": "type: team\nname: a\nmaintainers: [x]\nparent: b\n",
            "b.yaml": "type: team\nname: b\nmaintainers: [x]\nparent: a\n",
        },
    )
    errors = messages(tmp_path, LEVEL_ERROR)
    assert len([m for m in errors if "cycle" in m]) == 1


def test_valid_team_hierarchy(tmp_path):
    write(
        tmp_path,
        {
            "a.yaml": "type: team\nname: a\nmaintainers: [x]\n",
            "b.yaml": "type: team\nname: b\nmaintainers: [x]\nparent: a\n",
        },
    )
    assert check_configuration(tmp_path) == []


@pytest.mark.parametrize(
    "repo, expected",
    [
        (
            "type: repository\nname: r\nteams: {devs: admin}\n",
            "'visibility' is mandatory",
        ),
        (
            "type: repository\nname: r\nvisibility: internal\nteams: {devs: admin}\n",
            "visibility must be",
        ),
        (
            "type: repository\nname: r\nvisibility: public\nteams: {ghosts: admin}\n",
            "'ghosts' is not defined",
        ),
        (
            "type: repository\nname: r\nvisibility: public\nteams: {devs: push}\n",
            "at least one admin team",
        ),
        ("type: repository\nname: r\nvisibility: public\n", "at least one admin team"),
        (
            "type: repository\nname: r\nvisibility: public\nteams: {devs: admin}\n"
            "users: {bob: moderate}\n",
            "invalid access right 'moderate'",
        ),
        (
            "type: repository\nname: r\nvisibility: public\nteams: {devs: owner}\n",
            "invalid access right 'owner'",
        ),
        (
            "type: repository\nname: r\nvisibility: public\nteams: {devs: admin}\n"
            "forked: not-a-slug\n",
            "'forked' must be",
        ),
    ],
)
def test_repository_errors(tmp_path, repo, expected):
    write(tmp_path, {"devs.yaml": VALID_TEAM, "r.yaml": repo})
    assert any(expected in m for m in messages(tmp_path, LEVEL_ERROR))


def test_repository_duplicate_name(tmp_path):
    write(
        tmp_path,
        {"devs.yaml": VALID_TEAM, "r1.yaml": VALID_REPO, "r2.yaml": VALID_REPO},
    )
    assert any("defined more than once" in m for m in messages(tmp_path, LEVEL_ERROR))


def test_users_only_warn(tmp_path):
    repo = VALID_REPO + "users:\n  bob: push\nforked: octo/upstream\n"
    write(tmp_path, {"devs.yaml": VALID_TEAM, "r.yaml": repo})
    assert messages(tmp_path, LEVEL_ERROR) == []
    assert any("individual users" in m for m in messages(tmp_path, LEVEL_WARNING))


def test_validate_empty_config():
    config, issues = load_config(Path("/nonexistent-dir-for-gom"))
    assert issues and validate(config) == []


def test_cli_check_ok_and_warning(tmp_path, caplog):
    write(
        tmp_path,
        {"devs.yaml": VALID_TEAM, "r.yaml": VALID_REPO + "users:\n  bob: push\n"},
    )
    result = CliRunner().invoke(main, ["check", str(tmp_path)])
    assert result.exit_code == 0
    assert "individual users" in caplog.text
    assert "configuration is valid" in caplog.text


def test_cli_check_fails_on_error(tmp_path, caplog):
    write(tmp_path, {"devs.yaml": "type: team\nname: devs\nmaintainers: []\n"})
    result = CliRunner().invoke(main, ["check", str(tmp_path)])
    assert result.exit_code == 1
    assert "at least one maintainer" in caplog.text


def test_cli_check_missing_directory(tmp_path):
    result = CliRunner().invoke(main, ["check", str(tmp_path / "missing")])
    assert result.exit_code != 0
