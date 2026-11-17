from __future__ import annotations

from typing import Dict

from c2c_gh_scripts.github_repository_update import (
    RepositoryUpdate,
    apply_repository_updates,
)


class FakeOrg:
    def __init__(self) -> None:
        self.repos: Dict[str, FakeRepo] = {}

    def get_repo(self, name: str) -> "FakeRepo":
        return self.repos[name]

    def get_teams(self):  # noqa: D401, ANN201 - not needed for this dry-run test
        """Return no teams by default (not used in these tests)."""

        return []

    @property
    def login(self) -> str:  # noqa: D401, ANN201
        """Fake organisation login."""

        return "fake-org"


class FakeRepo:
    def __init__(self, name: str) -> None:
        self.name = name
        self.archived = False
        self.topics_calls: list[list[str]] = []
        self.permissions_calls: list[tuple[str, str]] = []
        self.archived_flag_set = False

    def get_topics(self) -> list[str]:
        return []

    def replace_topics(self, topics: list[str]) -> None:
        self.topics_calls.append(list(topics))

    def edit(self, archived: bool = False) -> None:  # noqa: FBT001
        if archived:
            self.archived_flag_set = True


class FakeOrgClientWrapper:
    """Helper to inject a FakeOrg into apply_repository_updates via monkeypatch."""

    def __init__(self, org: FakeOrg) -> None:
        self.org = org

    def get_organization(self, organisation: str) -> FakeOrg:  # noqa: ARG002
        return self.org


def test_apply_repository_updates_dry_run_does_not_mutate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Prepare fake organisation and repository.
    org = FakeOrg()
    repo = FakeRepo("repo1")
    org.repos["repo1"] = repo

    # Monkeypatch _build_github_client to return a wrapper that yields our org.
    import c2c_gh_scripts.github_repository_update as modu

    def fake_build_client() -> FakeOrgClientWrapper:
        return FakeOrgClientWrapper(org)

    monkeypatch.setattr(modu, "_build_github_client", fake_build_client)

    updates = {
        "repo1": RepositoryUpdate(
            department="BS",
            add_teams="some-team:admin",
            archive=True,
        )
    }

    # Run in dry-run mode: no repo methods that mutate state should be called.
    errors = apply_repository_updates("fake-org", updates, dry_run=True)

    assert errors == []
    assert repo.topics_calls == []
    assert not repo.archived_flag_set
