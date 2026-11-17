"""Loading and writing of the YAML configuration files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .models import LEVEL_ERROR, Issue, OrgConfig, Repository, Team

YAML_SUFFIXES = (".yml", ".yaml")

TEAM_FIELDS = {"type", "name", "maintainers", "members", "parent"}
REPOSITORY_FIELDS = {
    "type",
    "name",
    "visibility",
    "topics",
    "description",
    "teams",
    "users",
    "archived",
    "forked",
}


def find_config_files(path: Path) -> List[Path]:
    """Return the YAML files under ``path`` (recursively), sorted."""
    return sorted(
        p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in YAML_SUFFIXES
    )


def load_config(path: Path) -> Tuple[OrgConfig, List[Issue]]:
    """Load all the records found under ``path``.

    Parameters
    ----------
    path: Path
        Directory containing the YAML definition files.

    Returns
    -------
    tuple[OrgConfig, list[Issue]]
        The records which could be parsed, and the problems found while
        parsing. Semantic rules are checked by ``validation.validate``.
    """
    config = OrgConfig()
    issues: List[Issue] = []
    if not path.is_dir():
        issues.append(Issue(LEVEL_ERROR, "not a directory", str(path)))
        return config, issues

    for file in find_config_files(path):
        _load_file(file, path, config, issues)
    return config, issues


def _load_file(file: Path, root: Path, config: OrgConfig, issues: List[Issue]) -> None:
    name = str(file.relative_to(root))
    try:
        documents = list(yaml.safe_load_all(file.read_text(encoding="utf-8")))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        issues.append(Issue(LEVEL_ERROR, f"invalid YAML: {exc}", name))
        return

    for index, document in enumerate(documents, start=1):
        if document is None:
            continue
        source = f"{name} (document {index})" if len(documents) > 1 else name
        record = _parse_record(document, source, issues)
        if isinstance(record, Team):
            config.teams.append(record)
        elif isinstance(record, Repository):
            config.repositories.append(record)


def _parse_record(document: Any, source: str, issues: List[Issue]):
    if not isinstance(document, dict):
        issues.append(Issue(LEVEL_ERROR, "a record must be a mapping", source))
        return None
    record_type = document.get("type")
    if record_type == "team":
        return _parse_team(document, source, issues)
    if record_type == "repository":
        return _parse_repository(document, source, issues)
    issues.append(
        Issue(
            LEVEL_ERROR,
            f"unknown or missing record type {record_type!r} "
            "(expected 'team' or 'repository')",
            source,
        )
    )
    return None


def _check_fields(
    document: Dict[str, Any], allowed: set, source: str, issues: List[Issue]
) -> bool:
    ok = True
    for key in document:
        if key not in allowed:
            issues.append(Issue(LEVEL_ERROR, f"unknown field {key!r}", source))
            ok = False
    return ok


def _get_str(
    document: Dict[str, Any],
    key: str,
    default: str,
    source: str,
    issues: List[Issue],
) -> Tuple[str, bool]:
    value = document.get(key, default)
    if value is None:
        return default, True
    if not isinstance(value, str):
        issues.append(Issue(LEVEL_ERROR, f"field {key!r} must be a string", source))
        return default, False
    return value, True


def _get_str_list(
    document: Dict[str, Any], key: str, source: str, issues: List[Issue]
) -> Tuple[List[str], bool]:
    value = document.get(key)
    if value is None:
        return [], True
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        issues.append(
            Issue(LEVEL_ERROR, f"field {key!r} must be a list of strings", source)
        )
        return [], False
    return list(value), True


def _get_str_map(
    document: Dict[str, Any], key: str, source: str, issues: List[Issue]
) -> Tuple[Dict[str, str], bool]:
    value = document.get(key)
    if value is None:
        return {}, True
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        issues.append(
            Issue(
                LEVEL_ERROR,
                f"field {key!r} must be a mapping of strings to strings",
                source,
            )
        )
        return {}, False
    return dict(value), True


def _parse_team(document: Dict[str, Any], source: str, issues: List[Issue]):
    ok = _check_fields(document, TEAM_FIELDS, source, issues)
    name, name_ok = _get_str(document, "name", "", source, issues)
    if name_ok and not name:
        issues.append(Issue(LEVEL_ERROR, "team 'name' is required", source))
        name_ok = False
    maintainers, m_ok = _get_str_list(document, "maintainers", source, issues)
    members, mem_ok = _get_str_list(document, "members", source, issues)
    parent, p_ok = _get_str(document, "parent", "", source, issues)
    if not (ok and name_ok and m_ok and mem_ok and p_ok):
        return None
    return Team(
        name=name,
        maintainers=maintainers,
        members=members,
        parent=parent,
        source=source,
    )


def _parse_repository(document: Dict[str, Any], source: str, issues: List[Issue]):
    ok = _check_fields(document, REPOSITORY_FIELDS, source, issues)
    name, name_ok = _get_str(document, "name", "", source, issues)
    if name_ok and not name:
        issues.append(Issue(LEVEL_ERROR, "repository 'name' is required", source))
        name_ok = False
    visibility, v_ok = _get_str(document, "visibility", "", source, issues)
    description, d_ok = _get_str(document, "description", "", source, issues)
    forked, f_ok = _get_str(document, "forked", "", source, issues)
    topics, t_ok = _get_str_list(document, "topics", source, issues)
    teams, te_ok = _get_str_map(document, "teams", source, issues)
    users, u_ok = _get_str_map(document, "users", source, issues)
    archived = document.get("archived", False)
    if archived is None:
        archived = False
    a_ok = isinstance(archived, bool)
    if not a_ok:
        issues.append(Issue(LEVEL_ERROR, "field 'archived' must be a boolean", source))
    if not (
        ok and name_ok and v_ok and d_ok and f_ok and t_ok and te_ok and u_ok and a_ok
    ):
        return None
    return Repository(
        name=name,
        visibility=visibility,
        description=description,
        topics=topics,
        teams=teams,
        users=users,
        archived=archived,
        forked=forked,
        source=source,
    )


def _file_stem(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", name).lstrip(".") or "_"


def team_to_dict(team: Team) -> Dict[str, Any]:
    """Return the YAML representation of a team (stable key order)."""
    data: Dict[str, Any] = {
        "type": "team",
        "name": team.name,
        "maintainers": sorted(team.maintainers),
        "members": sorted(team.members),
    }
    if team.parent:
        data["parent"] = team.parent
    return data


def repository_to_dict(repo: Repository) -> Dict[str, Any]:
    """Return the YAML representation of a repository (stable key order)."""
    data: Dict[str, Any] = {
        "type": "repository",
        "name": repo.name,
        "visibility": repo.visibility,
        "description": repo.description,
        "topics": sorted(repo.topics),
        "teams": dict(sorted(repo.teams.items())),
    }
    if repo.users:
        data["users"] = dict(sorted(repo.users.items()))
    if repo.archived:
        data["archived"] = True
    if repo.forked:
        data["forked"] = repo.forked
    return data


def dump_record(record: Dict[str, Any]) -> str:
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True)


def write_config(config: OrgConfig, path: Path) -> List[Path]:
    """Write one file per team and repository under ``path``.

    Teams go to ``teams/<name>.yaml`` and repositories to
    ``repos/<name>.yaml``. Existing files are overwritten.

    Returns
    -------
    list[Path]
        The files written.
    """
    written: List[Path] = []
    for subdir, records in (
        ("teams", [(t.name, team_to_dict(t)) for t in config.teams]),
        ("repos", [(r.name, repository_to_dict(r)) for r in config.repositories]),
    ):
        for name, data in records:
            target = path / subdir / f"{_file_stem(name)}.yaml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dump_record(data), encoding="utf-8")
            written.append(target)
    return written
