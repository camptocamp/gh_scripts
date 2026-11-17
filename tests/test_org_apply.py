from __future__ import annotations

from types import SimpleNamespace as NS

from click.testing import CliRunner

from c2c_gh_scripts import github_org_manager
from c2c_gh_scripts.github_org_manager import main
from c2c_gh_scripts.org_manager import diff
from c2c_gh_scripts.org_manager.diff import compute_changes
from c2c_gh_scripts.org_manager.models import (
    OrgConfig,
    OrgState,
    Repository,
    SeatInfo,
    Team,
)
from c2c_gh_scripts.org_manager.state import load_org_state


def team(name, maintainers=("boss",), members=(), parent=""):
    return Team(name, list(maintainers), list(members), parent)


def repo(name, **kw):
    kw.setdefault("visibility", "private")
    kw.setdefault("teams", {"core": "admin"})
    return Repository(name, **kw)


def state(teams=(), repos=(), members=("boss",), **kw):
    return OrgState(OrgConfig(list(teams), list(repos)), members=list(members), **kw)


def descriptions(plan):
    return [c.describe() for c in plan.changes]


def run(desired_teams=(), desired_repos=(), actual=None, **flags):
    return compute_changes(
        OrgConfig(list(desired_teams), list(desired_repos)),
        actual or state(),
        **flags,
    )


def test_no_change_when_in_sync():
    t = team("core", members=["Bob"])
    r = repo("tool", description="d", topics=["a"])
    actual = state([team("core", members=["bob"])], [r], members=["boss", "bob"])
    assert run([t], [r], actual).changes == []


def test_create_team_parents_first_and_memberships():
    actual = state(members=["boss"])
    plan = run(
        [team("child", parent="core"), team("core", members=["bob"])],
        actual=actual,
    )
    assert descriptions(plan)[:2] == [
        "create team core",
        "create team child (parent: core)",
    ]
    assert "invite bob to the organization and add to team core as member" in (
        descriptions(plan)
    )
    assert "add boss to team child as maintainer" in descriptions(plan)


def test_team_membership_changes():
    actual = state(
        [team("core", maintainers=["boss"], members=["bob", "stale"], parent="old")],
        members=["boss", "bob", "stale", "carol"],
    )
    plan = run(
        [team("core", maintainers=["boss", "bob"], members=["carol"])], actual=actual
    )
    got = set(descriptions(plan))
    assert "remove parent of team core" in got
    assert "change role of bob in team core: member -> maintainer" in got
    assert "add carol to team core as member" in got
    assert "remove stale from team core" in got


def test_pending_invitation_counts_as_invited():
    actual = state(members=["boss"], pending_invitations=["Newbie"])
    plan = run([team("core", members=["newbie"])], actual=actual)
    assert not any("newbie" in d.lower() for d in descriptions(plan))


def test_seats_limit_invitations():
    actual = state(members=["boss"], seats=SeatInfo(total=10, filled=9))
    plan = run([team("core", members=["zoe", "amy", "bob"])], actual=actual)
    text = descriptions(plan)
    assert "invite amy to the organization and add to team core as member" in text
    assert not any("bob" in d or "zoe" in d for d in text)
    messages = [i.message for i in plan.issues]
    assert any("2 additional seat(s) required" in m for m in messages)
    assert any("no seat available: bob" in m for m in messages)
    assert any("no seat available: zoe" in m for m in messages)


def test_enough_seats_and_unknown_seats():
    plan = run(
        [team("core", members=["amy"])],
        actual=state(seats=SeatInfo(total=10, filled=2)),
    )
    assert plan.issues == []
    plan = run([team("core", members=["amy"])], actual=state(seats=None))
    assert any(
        "seats of the organization are unknown" in i.message for i in plan.issues
    )
    # no invitation needed: no seat complaint at all
    plan = run([team("core")], actual=state(seats=None))
    assert plan.issues == []


def test_prune_team():
    actual = state([team("core"), team("old")])
    assert descriptions(run([team("core")], actual=actual)) == []
    plan = run([team("core")], actual=actual, prune_teams=True)
    assert descriptions(plan) == ["delete team old"]


def test_create_repository_and_archive():
    plan = run(
        [team("core")],
        [repo("new", forked="octo/up", topics=["x"], archived=True)],
        actual=state([team("core")]),
    )
    text = descriptions(plan)
    assert text[0].startswith("create repository new (private) as a fork of octo/up")
    assert text[-1] == "archive repository new"


def test_update_repository_settings_and_access():
    current = repo(
        "tool",
        description="old",
        topics=["a", "b"],
        teams={"core": "push", "gone": "pull"},
        users={"Bob": "pull", "eve": "push"},
    )
    wanted = repo(
        "tool",
        visibility="public",
        description="new",
        topics=["b", "c"],
        teams={"core": "admin", "other": "pull"},
        users={"bob": "push"},
    )
    plan = run([team("core")], [wanted], state([team("core")], [current]))
    text = descriptions(plan)
    assert any(
        d.startswith("update repository tool") and "visibility" in d and "topics" in d
        for d in text
    )
    assert "change access of team core on tool: push -> admin" in text
    assert "grant team other pull access on tool" in text
    assert "remove access of team gone on tool" in text
    assert "change access of user bob on tool: pull -> push" in text
    assert "remove access of user eve on tool" in text


def test_archived_repositories():
    archived = repo("a", archived=True, description="old")
    wanted_archived = repo("a", archived=True, description="new")
    plan = run([team("core")], [wanted_archived], state([team("core")], [archived]))
    assert plan.changes == []
    assert any(
        "is archived, skipped changes" in i.message and "description" in i.message
        for i in plan.issues
    )

    wanted_active = repo("a", description="new")
    plan = run([team("core")], [wanted_active], state([team("core")], [archived]))
    text = descriptions(plan)
    assert text[0] == "unarchive repository a"
    assert text[1].startswith("update repository a")

    active = repo("a", description="old")
    plan = run([team("core")], [wanted_archived], state([team("core")], [active]))
    text = descriptions(plan)
    assert text[0].startswith("update repository a")
    assert text[-1] == "archive repository a"


def test_fork_mismatch_is_an_error_and_skips_repo():
    current = repo("f", description="old")
    wanted = repo("f", description="new", forked="octo/up")
    plan = run([team("core")], [wanted], state([team("core")], [current]))
    assert plan.changes == []
    assert any(i.level == "ERROR" and "fork status" in i.message for i in plan.issues)


def test_unmanaged_repository_warns_with_content_or_is_pruned():
    unmanaged = repo("legacy", description="old thing")
    actual = state([team("core")], [unmanaged])
    plan = run([team("core")], actual=actual)
    assert plan.changes == []
    (issue,) = plan.issues
    assert issue.level == "WARNING"
    assert "name: legacy" in issue.message and "type: repository" in issue.message

    plan = run([team("core")], actual=actual, prune_repos=True)
    assert descriptions(plan) == ["delete repository legacy"]
    assert plan.issues == []


def test_prune_users():
    actual = state(
        [team("core", members=["bob"])],
        members=["boss", "bob", "drifter", "theowner"],
        owners=["TheOwner"],
        outside_collaborators=["ext1", "ext2"],
    )
    wanted = [repo("tool", users={"EXT1": "pull"})]
    plan = run([team("core", members=["bob"])], wanted, actual)
    assert plan.changes and not any("remove" in d for d in descriptions(plan))

    plan = run([team("core", members=["bob"])], wanted, actual, prune_users=True)
    text = descriptions(plan)
    assert "remove drifter from the organization" in text
    assert "remove outside collaborator ext2 from all repositories" in text
    assert not any("theowner" in d or "bob from" in d or "ext1 from" in d for d in text)
    assert not any("boss from the" in d for d in text)


def test_prune_users_refused_without_teams():
    plan = run([], [], state(members=["boss", "x"]), prune_users=True)
    assert plan.changes == []
    assert any(i.level == "ERROR" for i in plan.issues)


def test_changes_are_ordered():
    actual = state(
        [team("core"), team("old")],
        [repo("legacy")],
        members=["boss", "drifter"],
    )
    plan = run(
        [team("core"), team("fresh")],
        [repo("tool", teams={"fresh": "admin"})],
        actual,
        prune_teams=True,
        prune_repos=True,
        prune_users=True,
    )
    kinds = [type(c).__name__ for c in plan.changes]
    assert kinds.index("CreateTeam") < kinds.index("CreateRepository")
    assert kinds.index("CreateRepository") < kinds.index("DeleteTeam")
    assert kinds[-1] == "RemoveOrgMember"
    assert isinstance(plan.changes[0], diff.Change)


class FakeOrg:
    def __init__(self, plan=None):
        self.plan = plan

    def get_teams(self):
        return []

    def get_repos(self):
        return []

    def get_members(self, role=None):
        names = ["Owner"] if role == "admin" else ["Owner", "bob"]
        return [NS(login=n) for n in names]

    def get_outside_collaborators(self):
        return [NS(login="ext")]

    def invitations(self):
        return [NS(login="pending"), NS(login=None, email="a@b.c")]


class FakeGithub:
    def __init__(self, org):
        self.org = org

    def get_organization(self, name):
        return self.org


def test_load_org_state_extras():
    gh = FakeGithub(FakeOrg(NS(seats=5, filled_seats=3)))
    loaded, issues = load_org_state(gh, "acme")
    assert loaded.members == ["Owner", "bob"]
    assert loaded.owners == ["Owner"]
    assert loaded.outside_collaborators == ["ext"]
    assert loaded.pending_invitations == ["pending"]
    assert loaded.seats.available == 2
    loaded, _ = load_org_state(FakeGithub(FakeOrg(None)), "acme")
    assert loaded.seats is None


CONFIG = """\
type: team
name: core
maintainers: [Owner]
members: [newbie]
---
type: repository
name: tool
visibility: private
teams: {core: admin}
"""


def test_cli_apply_dry_run(tmp_path, monkeypatch, caplog):
    (tmp_path / "c.yaml").write_text(CONFIG)
    gh = FakeGithub(FakeOrg(NS(seats=5, filled_seats=5)))
    monkeypatch.setattr(github_org_manager, "_build_github_client", lambda: gh)
    result = CliRunner().invoke(
        main, ["apply", "-n", "--prune-user", "--org", "acme", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "[dry-run] create team core" in caplog.text
    assert "create repository tool" in caplog.text
    assert "remove bob from the organization" in caplog.text
    assert "1 additional seat(s) required" in caplog.text


def test_cli_apply_invalid_config_does_not_query_github(tmp_path, monkeypatch, caplog):
    (tmp_path / "c.yaml").write_text("type: team\nname: core\nmaintainers: []\n")

    def boom():
        raise AssertionError("GitHub must not be queried")

    monkeypatch.setattr(github_org_manager, "_build_github_client", boom)
    result = CliRunner().invoke(main, ["apply", "-n", "--org", "acme", str(tmp_path)])
    assert result.exit_code == 1
    assert "at least one maintainer" in caplog.text


def test_cli_apply_real_run_not_yet_available(tmp_path):
    result = CliRunner().invoke(main, ["apply", "--org", "acme", str(tmp_path)])
    assert result.exit_code == 1
    assert "not implemented" in result.output
