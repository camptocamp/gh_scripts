from __future__ import annotations

from types import SimpleNamespace as NS

import yaml
from github import UnknownObjectException
from click.testing import CliRunner

from c2c_gh_scripts import github_org_manager
from c2c_gh_scripts.github_org_manager import generate_configuration, main
from c2c_gh_scripts.org_manager.config import load_config
from c2c_gh_scripts.org_manager.validation import validate


def user(login, role_name=None, **permissions):
    return NS(login=login, role_name=role_name, permissions=NS(**permissions))


class FakeTeam:
    def __init__(self, name, maintainers=(), members=(), parent=None, permission=None):
        self.name = name
        self.parent = parent
        self.permission = permission
        self._members = {"maintainer": maintainers, "member": members}

    def get_members(self, role):
        return [NS(login=login) for login in self._members[role]]


class FakeRepo:
    def __init__(self, name, **kw):
        self.name = name
        self.private = kw.get("private", True)
        self.visibility = kw.get("visibility", "private")
        self.description = kw.get("description")
        self.archived = kw.get("archived", False)
        self.fork = kw.get("fork", False)
        self.parent = kw.get("parent")
        self._topics = kw.get("topics", [])
        self._teams = kw.get("teams", [])
        self._users = kw.get("users", [])

    def get_topics(self):
        return self._topics

    def get_teams(self):
        return self._teams

    def get_collaborators(self, affiliation):
        assert affiliation == "direct"
        return self._users


class FakeGithub:
    def __init__(self, teams, repos):
        def get_team_by_slug(slug):
            for t in teams:
                if t.name.lower().replace(" ", "-") == slug:
                    return t
            raise UnknownObjectException(404)

        def get_repo(name):
            for r in repos:
                if r.name == name:
                    return r
            raise UnknownObjectException(404)

        self._org = NS(
            get_teams=lambda: teams,
            get_repos=lambda: repos,
            get_team_by_slug=get_team_by_slug,
            get_repo=get_repo,
        )

    def get_organization(self, name):
        assert name == "acme"
        return self._org


def make_github():
    core = FakeTeam("core", maintainers=["bob", "alice"], members=["zed"])
    sub = FakeTeam("sub team", maintainers=["carol"], parent=core)
    repos = [
        FakeRepo(
            "tool",
            description="A tool",
            topics=["python", "cli"],
            teams=[
                FakeTeam("sub team", permission="push"),
                FakeTeam("core", permission="admin"),
            ],
            users=[user("dave", role_name="write")],
        ),
        FakeRepo(
            "forked",
            visibility="public",
            archived=True,
            fork=True,
            parent=NS(full_name="octo/upstream"),
            teams=[FakeTeam("core", permission="admin")],
        ),
    ]
    return FakeGithub([core, sub], repos)


def test_generate_writes_one_file_per_record(tmp_path):
    count, issues = generate_configuration(make_github(), "acme", tmp_path)
    assert count == 4
    assert sorted(p.name for p in (tmp_path / "teams").iterdir()) == [
        "core.yaml",
        "sub team.yaml",
    ]
    tool = yaml.safe_load((tmp_path / "repos" / "tool.yaml").read_text())
    assert tool == {
        "type": "repository",
        "name": "tool",
        "visibility": "private",
        "description": "A tool",
        "topics": ["cli", "python"],
        "teams": {"core": "admin", "sub team": "push"},
        "users": {"dave": "push"},
    }
    forked = yaml.safe_load((tmp_path / "repos" / "forked.yaml").read_text())
    assert forked["archived"] is True and forked["forked"] == "octo/upstream"
    sub = yaml.safe_load((tmp_path / "teams" / "sub team.yaml").read_text())
    assert sub["parent"] == "core"
    assert any("individual users" in i.message for i in issues)


def test_generated_output_round_trips_through_check(tmp_path):
    generate_configuration(make_github(), "acme", tmp_path)
    config, load_issues = load_config(tmp_path)
    assert load_issues == []
    assert [i for i in validate(config) if i.level == "ERROR"] == []
    assert {t.name for t in config.teams} == {"core", "sub team"}


def test_generate_filters_and_missing_names(tmp_path):
    count, issues = generate_configuration(
        make_github(), "acme", tmp_path, ("tool", "ghost"), ("core",)
    )
    assert count == 2
    assert (tmp_path / "teams" / "core.yaml").exists()
    assert (tmp_path / "repos" / "tool.yaml").exists()
    assert not (tmp_path / "repos" / "forked.yaml").exists()
    assert any("'ghost' not found" in i.message for i in issues)
    # partial exports are not validated: no complaint about missing teams
    assert not any(i.level == "ERROR" for i in issues)


def test_generate_overwrites_existing_files(tmp_path):
    (tmp_path / "teams").mkdir()
    (tmp_path / "teams" / "core.yaml").write_text("stale: true\n")
    generate_configuration(make_github(), "acme", tmp_path)
    assert "stale" not in (tmp_path / "teams" / "core.yaml").read_text()


def test_unsupported_permissions_and_visibility_warn(tmp_path):
    repo = FakeRepo(
        "odd",
        visibility="internal",
        teams=[
            FakeTeam("core", permission="custom-role"),
            FakeTeam("core", permission="admin"),
        ],
        users=[
            user("eve", role_name="custom-role"),
            user("fay", read=False, push=True),
        ],
    )
    gh = FakeGithub([FakeTeam("core", maintainers=["a"])], [repo])
    _, issues = generate_configuration(gh, "acme", tmp_path)
    text = " ".join(i.message for i in issues)
    assert "visibility 'internal'" in text
    assert "'custom-role'" in text
    assert "user 'eve'" in text
    saved = yaml.safe_load((tmp_path / "repos" / "odd.yaml").read_text())
    assert saved["visibility"] == "private"
    assert saved["users"] == {"fay": "push"}


def test_cli_generate(tmp_path, monkeypatch):
    monkeypatch.setattr(github_org_manager, "_build_github_client", make_github)
    out = tmp_path / "out"
    result = CliRunner().invoke(
        main, ["generate", "--org", "acme", "-r", "tool", "-t", "core", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "repos" / "tool.yaml").exists()
    assert (out / "teams" / "core.yaml").exists()
