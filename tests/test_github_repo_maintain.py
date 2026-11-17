from __future__ import annotations

from typing import Any, List

import pytest

from c2c_gh_scripts.github_repo_maintain import (
    ActionAddTopic,
    ActionRemoveTopic,
    RuleBusinessOdooVersionTopic,
    _parse_odoo_version,
)


class FakeRepo:
    def __init__(self, name: str, topics: list[str] | None = None) -> None:
        self.name = name
        self.full_name = name
        self._topics = list(topics or [])
        self.replaced_topics: list[list[str]] = []

    def get_topics(self) -> list[str]:
        return list(self._topics)

    def replace_topics(self, topics: list[str]) -> None:
        # Simulate the PyGithub behaviour: store the last topics value.
        self._topics = list(topics)
        self.replaced_topics.append(list(topics))


class FakeContentFile:
    def __init__(self, decoded_content: bytes) -> None:
        self.decoded_content = decoded_content


class FakeRepoWithVersion(FakeRepo):
    def __init__(self, name: str, topics: list[str], version: str) -> None:
        super().__init__(name, topics)
        self.default_branch = "main"
        self._version = version

    def get_contents(self, path: str, ref: str | None = None) -> Any:  # noqa: ARG002
        assert path == "odoo/VERSION"
        return FakeContentFile(self._version.encode("utf-8"))


def test_parse_odoo_version_valid() -> None:
    assert _parse_odoo_version("16.0.0.0.0") == (16, 0, 0, 0, 0)
    assert _parse_odoo_version("  15.1.2.3.4  ") == (15, 1, 2, 3, 4)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "1",
        "1.2.3.4",
        "1.2.3.4.5.6",
        "a.b.c.d.e",
    ],
)
def test_parse_odoo_version_invalid(raw: str) -> None:
    assert _parse_odoo_version(raw) is None


def test_action_add_topic_adds_when_missing() -> None:
    repo = FakeRepo("test-repo", topics=["foo"])

    action = ActionAddTopic(repo, "bar")
    action.run()

    assert "bar" in repo.get_topics()
    # replace_topics should have been called exactly once.
    assert repo.replaced_topics[-1] == ["foo", "bar"]


def test_action_add_topic_dry_run_does_not_mutate() -> None:
    repo = FakeRepo("test-repo", topics=["foo"])

    action = ActionAddTopic(repo, "bar")
    action.run(dry_run=True)

    assert repo.replaced_topics == []
    assert repo.get_topics() == ["foo"]


def test_action_add_topic_idempotent_when_present() -> None:
    repo = FakeRepo("test-repo", topics=["foo"])

    action = ActionAddTopic(repo, "foo")
    action.run()

    # No additional replace_topics call should have happened.
    assert repo.replaced_topics == []
    assert repo.get_topics() == ["foo"]


def test_action_remove_topic_removes_when_present() -> None:
    repo = FakeRepo("test-repo", topics=["foo", "bar"])

    action = ActionRemoveTopic(repo, "bar")
    action.run()

    assert repo.get_topics() == ["foo"]
    assert repo.replaced_topics[-1] == ["foo"]


def test_action_remove_topic_dry_run_does_not_mutate() -> None:
    repo = FakeRepo("test-repo", topics=["foo", "bar"])

    action = ActionRemoveTopic(repo, "bar")
    action.run(dry_run=True)

    assert repo.replaced_topics == []
    assert repo.get_topics() == ["foo", "bar"]


def test_action_remove_topic_idempotent_when_missing() -> None:
    repo = FakeRepo("test-repo", topics=["foo"])

    action = ActionRemoveTopic(repo, "bar")
    action.run()

    # No calls when topic is not present.
    assert repo.replaced_topics == []
    assert repo.get_topics() == ["foo"]


def test_rule_business_odoo_version_topic_adds_and_cleans_topics() -> None:
    # business repo with outdated odoo-15 topic and valid VERSION 16.0.0.0.0
    repo = FakeRepoWithVersion(
        "test-repo",
        topics=["business", "odoo-15"],
        version="16.0.0.0.0",
    )

    rule = RuleBusinessOdooVersionTopic()
    actions: List[Any] = rule.evaluate(repo)

    # Expect: add odoo-project and odoo-16, remove odoo-15
    descriptions = sorted(a.describe() for a in actions)
    assert descriptions == [
        "Add topic 'odoo-16'",
        "Add topic 'odoo-project'",
        "Remove topic 'odoo-15'",
    ]
