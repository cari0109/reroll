"""Load and validate params.yaml (the action table and stat bounds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from lifegit.i18n import LocalizedText
from lifegit.models import StatBounds, StatName, State

DEFAULT_PARAMS_PATH = Path(__file__).with_name("params.yaml")


class TagSpec(BaseModel):
    name: str
    duration: int = Field(gt=0)


class ActionSpec(BaseModel):
    description: LocalizedText
    effects: dict[StatName, tuple[int, int]]
    tags: list[TagSpec] = Field(default_factory=list)
    source: str

    @model_validator(mode="after")
    def _check_ranges(self) -> ActionSpec:
        for stat, (lo, hi) in self.effects.items():
            if lo > hi:
                raise ValueError(f"{stat}: lo ({lo}) > hi ({hi})")
        return self


class Params(BaseModel):
    stats: dict[StatName, StatBounds]
    initial_state: State
    actions: dict[str, ActionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_against_bounds(self) -> Params:
        for stat, bounds in self.stats.items():
            v = getattr(self.initial_state, stat)
            if not bounds.min <= v <= bounds.max:
                raise ValueError(f"initial_state.{stat}={v} out of [{bounds.min}, {bounds.max}]")
        for name, action in self.actions.items():
            for stat, (lo, hi) in action.effects.items():
                limit = self.stats[stat].max_delta
                if max(abs(lo), abs(hi)) > limit:
                    raise ValueError(
                        f"action {name!r}: {stat} range [{lo}, {hi}] exceeds max_delta {limit}"
                    )
        return self


def load_params(path: Path | None = None) -> Params:
    with open(path or DEFAULT_PARAMS_PATH, encoding="utf-8") as f:
        return Params.model_validate(yaml.safe_load(f))


@lru_cache(maxsize=1)
def default_params() -> Params:
    return load_params()
