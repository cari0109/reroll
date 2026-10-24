"""Load and validate params.yaml (the action table and stat bounds)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from reroll.i18n import LANGS, Lang, LocalizedText, t
from reroll.models import STAT_NAMES, StatBounds, StatName, State

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


class CustomAction(BaseModel):
    up: tuple[int, int]
    down: tuple[int, int]

    @model_validator(mode="after")
    def _check_signs(self) -> CustomAction:
        if not 0 < self.up[0] <= self.up[1] or not self.down[0] <= self.down[1] < 0:
            raise ValueError("custom_action.up must be positive and down negative, each as [lo, hi]")
        return self


CUSTOM_PREFIX = "custom:"
ARROW = {"+": "\u2191", "-": "\u2193"}


def custom_action(directions: dict[StatName, str]) -> str:
    """{'mood': '+', 'energy': '-'} -> 'custom:energy-,mood+' (stats in a fixed order)."""
    parts = [f"{s}{directions[s]}" for s in STAT_NAMES if directions.get(s) in ("+", "-")]
    if not parts:
        raise ValueError("a custom action needs at least one stat going up or down")
    return CUSTOM_PREFIX + ",".join(parts)


def parse_custom(action: str) -> dict[StatName, str] | None:
    """'custom:energy-,mood+' -> {'energy': '-', 'mood': '+'}; None if it isn't a valid custom action."""
    if not action.startswith(CUSTOM_PREFIX):
        return None
    out: dict[StatName, str] = {}
    for part in action[len(CUSTOM_PREFIX):].split(","):
        stat, sign = part[:-1], part[-1:]
        if stat not in STAT_NAMES or sign not in ("+", "-") or stat in out:
            return None
        out[stat] = sign  # type: ignore[index]
    return out or None


class Params(BaseModel):
    stats: dict[StatName, StatBounds]
    initial_state: State
    actions: dict[str, ActionSpec] = Field(min_length=1)
    daily_drift: dict[StatName, int] = Field(default_factory=dict)
    tags: dict[str, TagEffects]
    simulation: Simulation
    custom_action: CustomAction

    def is_action(self, name: str) -> bool:
        return name in self.actions or parse_custom(name) is not None

    def action(self, name: str) -> ActionSpec:
        """The spec for a table action or a player-defined custom one."""
        if name in self.actions:
            return self.actions[name]
        directions = parse_custom(name)
        if directions is None:
            raise KeyError(name)
        ranges = {"+": self.custom_action.up, "-": self.custom_action.down}
        arrows = {
            lang: " ".join(f"{t(f'stat.{s}', lang)}{ARROW[d]}" for s, d in directions.items()) for lang in LANGS
        }
        return ActionSpec(
            description=LocalizedText(en=f"Custom: {arrows['en']}", zh=f"自定义：{arrows['zh']}"),
            effects={s: ranges[d] for s, d in directions.items()},
            source="player-chosen directions; amounts from custom_action",
        )

    def describe(self, name: str, lang: Lang) -> str:
        return self.action(name).description.get(lang)

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
