"""Data models for life.json.

These only describe the shape of the data and check structural integrity.
How state changes is the job of the rules layer.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reroll.i18n import DEFAULT_LANG, Lang

StatName = Literal["energy", "mood", "money", "social", "goal"]
STAT_NAMES: tuple[StatName, ...] = ("energy", "mood", "money", "social", "goal")

Risk = Literal["low", "medium", "high"]


class StatBounds(BaseModel):
    min: int = 0
    max: int = 100
    max_delta: int = Field(15, gt=0, description="max change allowed in a single commit")

    @model_validator(mode="after")
    def _check_range(self) -> StatBounds:
        if self.min >= self.max:
            raise ValueError(f"min ({self.min}) must be < max ({self.max})")
        return self


class State(BaseModel):
    """Life state at a point in time. All stats are normalized to 0-100
    (money means "financial health", not an actual amount)."""

    energy: int
    mood: int
    money: int
    social: int
    goal: int


class Tag(BaseModel):
    """A history tag - the carrier of the butterfly effect. Expires on expires_day."""

    name: str
    count: int = Field(1, ge=1)
    since_day: int = Field(ge=0)
    expires_day: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_days(self) -> Tag:
        if self.expires_day < self.since_day:
            raise ValueError("expires_day must be >= since_day")
        return self


class Option(BaseModel):
    """One choice. The narrator writes `label` and picks `action` from the fixed
    action table; `effects` are computed by the rules layer."""

    id: str
    label: str
    action: str
    effects: dict[StatName, int] = Field(default_factory=dict)


class Commit(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{7}$")
    parent: str | None
    branch: str
    day: int = Field(ge=1)
    decision: str
    options: list[Option] = Field(min_length=2, max_length=4)
    chosen: str
    state_after: State
    tags_active: list[Tag] = Field(default_factory=list)
    narration: str = ""
    risk: Risk = "low"

    @model_validator(mode="after")
    def _check_chosen(self) -> Commit:
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate option ids: {ids}")
        if self.chosen not in ids:
            raise ValueError(f"chosen {self.chosen!r} not in options {ids}")
        return self

    @property
    def chosen_option(self) -> Option:
        return next(o for o in self.options if o.id == self.chosen)


class Branch(BaseModel):
    head: str | None = None
    created_from: str | None = None


class Meta(BaseModel):
    name: str
    created_at: date
    version: int = 1
    lang: Lang = DEFAULT_LANG


class Repo(BaseModel):
    """The whole life.json."""

    meta: Meta
    state_schema: dict[StatName, StatBounds]
    initial_state: State
    current_branch: str = "main"
    branches: dict[str, Branch] = Field(default_factory=lambda: {"main": Branch()})
    commits: list[Commit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_integrity(self) -> Repo:
        missing = set(STAT_NAMES) - set(self.state_schema)
        if missing:
            raise ValueError(f"state_schema missing stats: {sorted(missing)}")
        if self.current_branch not in self.branches:
            raise ValueError(f"current_branch {self.current_branch!r} does not exist")

        ids = {c.id for c in self.commits}
        if len(ids) != len(self.commits):
            raise ValueError("duplicate commit ids")
        for c in self.commits:
            if c.parent is not None and c.parent not in ids:
                raise ValueError(f"commit {c.id} has unknown parent {c.parent}")
        for name, b in self.branches.items():
            for ref in (b.head, b.created_from):
                if ref is not None and ref not in ids:
                    raise ValueError(f"branch {name!r} references unknown commit {ref}")
        return self

    def get_commit(self, commit_id: str) -> Commit:
        for c in self.commits:
            if c.id == commit_id:
                return c
        raise KeyError(commit_id)
