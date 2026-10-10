"""Load and validate params.yaml (the action table and stat bounds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from reroll.i18n import LocalizedText
from reroll.models import StatBounds, StatName, State

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


Habit = dict[str, float]  # action name -> weight multiplier


class TagEffects(BaseModel):
    carryover: dict[StatName, int] = Field(default_factory=dict)
    habit: Habit = Field(default_factory=dict)
    source: str


class LowStatRule(BaseModel):
    stat: StatName
    below: int
    habit: Habit
    source: str


class RiskProb(BaseModel):
    medium: float = Field(gt=0, lt=1)
    high: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _check_order(self) -> RiskProb:
        if self.medium >= self.high:
            raise ValueError("risk_prob.medium must be < risk_prob.high")
        return self


class Simulation(BaseModel):
    runs: int = Field(gt=0)
    horizon: int = Field(gt=0)
    base_weight: float = Field(gt=0)
    history_weight: float = Field(ge=0)
    danger_below: int
    risk_prob: RiskProb
    low_stat_rules: list[LowStatRule] = Field(default_factory=list)


class Params(BaseModel):
    stats: dict[StatName, StatBounds]
    initial_state: State
    actions: dict[str, ActionSpec] = Field(min_length=1)
    daily_drift: dict[StatName, int] = Field(default_factory=dict)
    tags: dict[str, TagEffects]
    simulation: Simulation

    @model_validator(mode="after")
    def _check_references(self) -> Params:
        for name, action in self.actions.items():
            for spec in action.tags:
                if spec.name not in self.tags:
                    raise ValueError(f"action {name!r} attaches tag {spec.name!r}, which is not in `tags`")
        habits = [(f"tag {n!r}", t.habit) for n, t in self.tags.items()]
        habits += [(f"low_stat_rule {r.stat}<{r.below}", r.habit) for r in self.simulation.low_stat_rules]
        for where, habit in habits:
            for action, factor in habit.items():
                if action not in self.actions:
                    raise ValueError(f"{where}: unknown action {action!r}")
                if factor <= 0:
                    raise ValueError(f"{where}: habit factor for {action!r} must be > 0")
        return self

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
