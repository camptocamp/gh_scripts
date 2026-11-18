from __future__ import annotations

from click.testing import CliRunner

from c2c_gh_scripts import github_org_manager
from c2c_gh_scripts.github_org_manager import main
from c2c_gh_scripts.org_manager.models import OrgConfig, Repository, Team
from c2c_gh_scripts.org_manager.report import build_report
from test_org_generate import make_github


def sample() -> OrgConfig:
    return OrgConfig(
        teams=[
            Team(name="empty"),
            Team(name="core", maintainers=["Alice"], members=["bob"]),
        ],
        repositories=[
            Repository(name="a", teams={"core": "admin"}, users={"alice": "push"}),
            Repository(name="b", teams={"core": "push"}, users={"carol": "pull"}),
            Repository(name="c", users={"carol": "admin", "dave": "pull"}),
        ],
    )


def test_report_sections():
    report = build_report(sample())
    assert "Empty teams (no members, no maintainers): 1\n  - empty\n" in report
    assert "  - carol (b, c)\n  - dave (c)\n" in report
    assert "alice (" not in report
    assert "Repositories without teams: 1\n  - c\n" in report
    assert "Repositories without an admin team: 2\n  - b\n  - c\n" in report


def test_cli_generate_report(tmp_path, monkeypatch):
    monkeypatch.setattr(github_org_manager, "_build_github_client", make_github)
    report = tmp_path / "report.txt"
    result = CliRunner().invoke(
        main,
        ["generate", "--org", "acme", "--report", str(report), str(tmp_path / "out")],
    )
    assert result.exit_code == 0, result.output
    assert "Empty teams" in result.output
    assert report.read_text().startswith("Empty teams")
