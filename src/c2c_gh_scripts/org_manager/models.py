"""Data models for the github-org-manager configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

ACCESS_LEVELS = ("pull", "triage", "push", "maintain", "admin")
VISIBILITIES = ("public", "private")

LEVEL_ERROR = "ERROR"
LEVEL_WARNING = "WARNING"


@dataclass
class Issue:
    """A problem found while loading or validating the configuration."""

    level: str
    message: str
    source: str = ""

    def __str__(self) -> str:
        prefix = f"{self.source}: " if self.source else ""
        return f"{self.level}: {prefix}{self.message}"


@dataclass
class Team:
    name: str
    maintainers: List[str] = field(default_factory=list)
    members: List[str] = field(default_factory=list)
    parent: str = ""
    source: str = ""


@dataclass
class Repository:
    name: str
    visibility: str = ""
    description: str = ""
    topics: List[str] = field(default_factory=list)
    teams: Dict[str, str] = field(default_factory=dict)
    users: Dict[str, str] = field(default_factory=dict)
    archived: bool = False
    forked: str = ""
    source: str = ""


@dataclass
class OrgConfig:
    """The target state of an organisation.

    Records are kept in lists so that duplicates can be reported by the
    validation step rather than silently overwritten.
    """

    teams: List[Team] = field(default_factory=list)
    repositories: List[Repository] = field(default_factory=list)


@dataclass
class SeatInfo:
    """Seats of the organisation plan."""

    total: int
    filled: int

    @property
    def available(self) -> int:
        return max(0, self.total - self.filled)


@dataclass
class OrgState:
    """The current state of an organisation, as read from GitHub."""

    config: OrgConfig = field(default_factory=OrgConfig)
    members: List[str] = field(default_factory=list)
    owners: List[str] = field(default_factory=list)
    outside_collaborators: List[str] = field(default_factory=list)
    pending_invitations: List[str] = field(default_factory=list)
    seats: Optional[SeatInfo] = None
