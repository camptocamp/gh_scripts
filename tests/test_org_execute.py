from __future__ import annotations

import logging
from types import SimpleNamespace as NS

from click.testing import CliRunner
from github import GithubException, RateLimitExceededException

from c2c_gh_scripts import github_org_manager
from c2c_gh_scripts.github_org_manager import main
from c2c_gh_scripts.org_manager import diff
from c2c_gh_scripts.org_manager.apply import Executor
from c2c_gh_scripts.org_manager.models import Repository

LOGGER = logging.getLogger("test-executor")


class FakeTeam:
    def __init__(self, name, log, team_id=1, members=()):
        self.name = name
        self.id = team_id
        self._log = log
        self._members = [NS(login=m) for m in members]

    def get_members(self):
        return list(self._members)

    def edit(self, name, **kw):
        self._log.append(("team.edit", self.name, kw))

    def add_membership(self, user, role):
        self._log.append(("team.add_membership", self.name, user.login, role))

    def remove_membership(self, user):
        self._log.append(("team.remove_membership", self.name, user.login))

    def delete(self):
        self._log.append(("team.delete", self.name))

    def update_team_repository(self, repo, permission):
        self._log.append(("team.update_repo", self.name, repo.name, permission))

    def remove_from_repos(self, repo):
        self._log.append(("team.remove_repo", self.name, repo.name))


class FakeRepo:
    def __init__(self, name, log, private=True, description=""):
        self.name = name
        self.private = private
        self.description = description
        self._log = log

    def edit(self, **kw):
        self._log.append(("repo.edit", self.name, kw))

    def replace_topics(self, topics):
        self._log.append(("repo.topics", self.name, topics))

    def add_to_collaborators(self, login, permission):
        self._log.append(("repo.add_collab", self.name, login, permission))

    def remove_from_collaborators(self, login):
        self._log.append(("repo.remove_collab", self.name, login))

    def delete(self):
        self._log.append(("repo.delete", self.name))

    def create_fork(self, organization, name):
        self._log.append(("repo.fork", self.name, organization, name))
        return FakeRepo(name, self._log, private=False)


class FakeOrg:
    def __init__(self, log, teams=(), repos=()):
        self._log = log
        self._teams = list(teams)
        self._repos = {r.name: r for r in repos}
        self.plan = NS(seats=50, filled_seats=1)

    def get_teams(self):
        return list(self._teams)

    def get_repos(self):
        return []

    def get_repo(self, name):
        return self._repos[name]

    def create_team(self, name, **kw):
        self._log.append(("org.create_team", name, kw))
        team = FakeTeam(
            name, self._log, team_id=100 + len(self._teams), members=["creator"]
        )
        self._teams.append(team)
        return team

    def create_repo(self, name, **kw):
        self._log.append(("org.create_repo", name, kw))
        return FakeRepo(name, self._log)

    def remove_from_membership(self, user):
        self._log.append(("org.remove_member", user.login))

    def remove_outside_collaborator(self, user):
        self._log.append(("org.remove_outside", user.login))

    def get_members(self, role=None):
        return [NS(login="owner")]

    def get_outside_collaborators(self):
        return []

    def invitations(self):
        return []


class FakeGithub:
    def __init__(self, org, log):
        self.org = org
        self._log = log

    def get_organization(self, name):
        return self.org

    def get_user(self, login):
        return NS(login=login)

    def get_repo(self, full_name):
        return FakeRepo(full_name.split("/")[1], self._log, private=False)


def test_team_changes():
    log = []
    core = FakeTeam("core", log, team_id=7)
    other = FakeTeam("other", log, team_id=8)
    ex = Executor(FakeGithub(FakeOrg(log, [core, other]), log), "acme", LOGGER)
    failures = ex.execute(
        [
            diff.CreateTeam("child", "core", ("bob",)),
            diff.SetTeamParent("other", ""),
            diff.SetTeamParent("other", "core"),
            diff.SetTeamMembership("core", "bob", "maintainer", invite=True),
            diff.RemoveTeamMember("core", "stale"),
            diff.DeleteTeam("other"),
        ]
    )
    assert failures == []
    assert log == [
        ("org.create_team", "child", {"privacy": "closed", "parent_team_id": 7}),
        ("team.remove_membership", "child", "creator"),
        ("team.edit", "other", {"parent_team_id": None}),
        ("team.edit", "other", {"parent_team_id": 7}),
        ("team.add_membership", "core", "bob", "maintainer"),
        ("team.remove_membership", "core", "stale"),
        ("team.delete", "other"),
    ]


def test_creator_is_kept_when_wanted():
    log = []
    ex = Executor(FakeGithub(FakeOrg(log), log), "acme", LOGGER)
    ex.execute([diff.CreateTeam("t", "", ("Creator",))])
    assert not any(entry[0] == "team.remove_membership" for entry in log)


def test_repository_changes():
    log = []
    core = FakeTeam("core", log)
    repo = FakeRepo("tool", log)
    org = FakeOrg(log, [core], [repo])
    ex = Executor(FakeGithub(org, log), "acme", LOGGER)
    failures = ex.execute(
        [
            diff.UnarchiveRepository("tool"),
            diff.UpdateRepository(
                "tool",
                (("visibility", "private", "public"), ("topics", ["a"], ["b"])),
            ),
            diff.SetTeamAccess("tool", "core", "push", "pull"),
            diff.RemoveTeamAccess("tool", "core"),
            diff.SetUserAccess("tool", "bob", "admin"),
            diff.RemoveUserAccess("tool", "eve"),
            diff.ArchiveRepository("tool"),
            diff.DeleteRepository("tool"),
            diff.RemoveOrgMember("drifter"),
            diff.RemoveOutsideCollaborator("ext"),
        ]
    )
    assert failures == []
    assert log == [
        ("repo.edit", "tool", {"archived": False}),
        ("repo.topics", "tool", ["b"]),
        ("repo.edit", "tool", {"visibility": "public"}),
        ("team.update_repo", "core", "tool", "push"),
        ("team.remove_repo", "core", "tool"),
        ("repo.add_collab", "tool", "bob", "admin"),
        ("repo.remove_collab", "tool", "eve"),
        ("repo.edit", "tool", {"archived": True}),
        ("repo.delete", "tool"),
        ("org.remove_member", "drifter"),
        ("org.remove_outside", "ext"),
    ]


def test_create_repository_and_fork():
    log = []
    core = FakeTeam("core", log)
    ex = Executor(FakeGithub(FakeOrg(log, [core]), log), "acme", LOGGER)
    new = Repository(
        "new",
        visibility="private",
        description="d",
        topics=["x"],
        teams={"core": "admin"},
        users={"bob": "push"},
    )
    fork = Repository("fk", visibility="private", forked="octo/up", description="mine")
    assert ex.execute([diff.CreateRepository(new), diff.CreateRepository(fork)]) == []
    assert log == [
        ("org.create_repo", "new", {"description": "d", "visibility": "private"}),
        ("repo.topics", "new", ["x"]),
        ("team.update_repo", "core", "new", "admin"),
        ("repo.add_collab", "new", "bob", "push"),
        ("repo.fork", "up", "acme", "fk"),
        ("repo.edit", "fk", {"visibility": "private", "description": "mine"}),
    ]


def test_failures_are_collected_and_execution_continues(caplog):
    log = []
    core = FakeTeam("core", log)

    def broken(user, role):
        raise GithubException(422, {"message": "boom"}, {})

    core.add_membership = broken
    ex = Executor(FakeGithub(FakeOrg(log, [core]), log), "acme", LOGGER)
    with caplog.at_level(logging.ERROR, logger="test-executor"):
        failures = ex.execute(
            [
                diff.SetTeamMembership("core", "bob", "member"),
                diff.SetTeamMembership("ghost", "bob", "member"),
                diff.RemoveTeamMember("core", "eve"),
            ]
        )
    assert [type(f.error).__name__ for f in failures] == [
        "GithubException",
        "ApplyError",
    ]
    assert ("team.remove_membership", "core", "eve") in log
    assert "HTTP 422: boom" in caplog.text
    assert "team 'ghost' does not exist" in caplog.text


def test_rate_limit_is_retried_then_gives_up():
    log = []
    core = FakeTeam("core", log)
    calls = []

    def limited(user, role):
        calls.append(1)
        if len(calls) < 3:
            raise RateLimitExceededException(
                403, {"message": "limit"}, {"retry-after": "7"}
            )
        log.append(("added", user.login))

    core.add_membership = limited
    sleeps = []
    ex = Executor(
        FakeGithub(FakeOrg(log, [core]), log), "acme", LOGGER, sleep=sleeps.append
    )
    assert ex.execute([diff.SetTeamMembership("core", "bob", "member")]) == []
    assert sleeps == [8.0, 8.0]
    assert ("added", "bob") in log

    def always(user, role):
        raise RateLimitExceededException(403, {"message": "limit"}, {})

    core.add_membership = always
    sleeps.clear()
    ex = Executor(
        FakeGithub(FakeOrg(log, [core]), log),
        "acme",
        LOGGER,
        sleep=sleeps.append,
        max_retries=2,
    )
    failures = ex.execute([diff.SetTeamMembership("core", "bob", "member")])
    assert len(failures) == 1 and len(sleeps) == 2


CONFIG = """\
type: team
name: core
maintainers: [owner]
---
type: repository
name: tool
visibility: private
teams: {core: admin}
"""


def test_cli_real_run(tmp_path, monkeypatch):
    (tmp_path / "c.yaml").write_text(CONFIG)
    log = []
    gh = FakeGithub(FakeOrg(log), log)
    monkeypatch.setattr(github_org_manager, "_build_github_client", lambda: gh)
    result = CliRunner().invoke(main, ["apply", "--org", "acme", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert [entry[0] for entry in log] == [
        "org.create_team",
        "team.remove_membership",
        "team.add_membership",
        "org.create_repo",
        "team.update_repo",
    ]


def test_cli_exit_status_on_failure(tmp_path, monkeypatch):
    (tmp_path / "c.yaml").write_text(CONFIG)
    log = []
    org = FakeOrg(log)

    def refuse(name, **kw):
        raise GithubException(403, {"message": "forbidden"}, {})

    org.create_team = refuse
    monkeypatch.setattr(
        github_org_manager, "_build_github_client", lambda: FakeGithub(org, log)
    )
    result = CliRunner().invoke(main, ["apply", "--org", "acme", str(tmp_path)])
    assert result.exit_code == 1
