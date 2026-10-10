"""Monte Carlo forecast: "the future is a superposition that hasn't collapsed yet".

From the current state we simulate many possible futures day by day, using the
same rules as real commits (rules.start_day + the action table). Which action a
simulated day takes is drawn from weights built from the player's own history,
active tag habits, and low-stat rules - all in params.yaml.

For entertainment only: the parameters are assumptions, not a model of real life.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass

from reroll import rules
from reroll.models import STAT_NAMES, Risk, StatName, State, Tag
from reroll.params import Params

# `goal` is a progress stat; being low on it isn't dangerous.
RISK_STATS: tuple[StatName, ...] = ("energy", "mood", "money", "social")
QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9)


@dataclass(frozen=True)
class Band:
    """Distribution of one stat on one future day."""

    p10: int
    p25: int
    p50: int
    p75: int
    p90: int


@dataclass(frozen=True)
class Forecast:
    start_day: int  # first simulated day
    runs: int
    bands: dict[StatName, list[Band]]  # bands[stat][i] is the stat at the end of start_day + i
    danger_prob: float
    risk: Risk
    paths: dict[StatName, list[list[int]]] | None = None  # paths[stat][run][i], only with keep_paths

    @property
    def days(self) -> int:
        return len(self.bands[STAT_NAMES[0]])

    def at(self, stat: StatName, day_offset: int) -> Band:
        """Band `day_offset` days ahead (1 = the first simulated day)."""
        return self.bands[stat][day_offset - 1]


def action_weights(state: State, tags: list[Tag], history: Counter[str], params: Params) -> dict[str, float]:
    sim = params.simulation
    weights = {a: sim.base_weight + sim.history_weight * history.get(a, 0) for a in params.actions}
    for tag in tags:
        for action, factor in params.tags[tag.name].habit.items():
            weights[action] *= factor
    for rule in sim.low_stat_rules:
        if getattr(state, rule.stat) < rule.below:
            for action, factor in rule.habit.items():
                weights[action] *= factor
    return weights


def simulate_day(
    state: State,
    tags: list[Tag],
    day: int,
    history: Counter[str],
    params: Params,
    rng: random.Random,
    action_name: str | None = None,
) -> tuple[State, list[Tag]]:
    """One simulated day. `action_name` forces the action; otherwise it is drawn from the habit weights."""
    state, tags, _ = rules.start_day(state, tags, day, params, params.stats)
    if action_name is None:
        weights = action_weights(state, tags, history, params)
        action_name = rng.choices(list(weights), weights=list(weights.values()))[0]
    action = params.actions[action_name]
    state = rules.apply_effects(state, rules.roll_effects(action, rng), params.stats)
    return state, rules.update_tags(tags, action, day)


def _quantile(sorted_values: list[int], q: float) -> int:
    return sorted_values[round(q * (len(sorted_values) - 1))]


def _seed(
    state: State, tags: list[Tag], day: int, history: Counter[str], days: int, runs: int, first_action: str | None
) -> int:
    """Same situation -> same forecast. Lets whatif branches and tests agree."""
    key = json.dumps(
        {
            "state": state.model_dump(),
            "tags": [t.model_dump() for t in tags],
            "day": day,
            "history": sorted(history.items()),
            "days": days,
            "runs": runs,
            "first_action": first_action,
        },
        sort_keys=True,
    )
    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)


def forecast(
    state: State,
    tags: list[Tag],
    start_day: int,
    history: Counter[str],
    params: Params,
    days: int | None = None,
    runs: int | None = None,
    first_action: str | None = None,
    keep_paths: bool = False,
) -> Forecast:
    """Simulate `runs` futures. With `first_action`, every run takes that action on the first day
    (its effect is still rolled per run), which shows where a choice tends to lead without
    revealing its actual outcome. `keep_paths` keeps every trajectory, for drawing."""
    sim = params.simulation
    days = days or sim.horizon
    runs = runs or sim.runs
    rng = random.Random(_seed(state, tags, start_day, history, days, runs, first_action))

    samples: dict[StatName, list[list[int]]] = {s: [[] for _ in range(days)] for s in STAT_NAMES}
    dangerous_runs = 0
    for _ in range(runs):
        s, t = state, tags
        in_danger = min(getattr(s, k) for k in RISK_STATS) < sim.danger_below
        for i in range(days):
            forced = first_action if i == 0 else None
            s, t = simulate_day(s, t, start_day + i, history, params, rng, forced)
            for stat in STAT_NAMES:
                samples[stat][i].append(getattr(s, stat))
            in_danger = in_danger or min(getattr(s, k) for k in RISK_STATS) < sim.danger_below
        dangerous_runs += in_danger

    bands = {
        stat: [Band(*(_quantile(sorted(day_values), q) for q in QUANTILES)) for day_values in per_day]
        for stat, per_day in samples.items()
    }
    danger_prob = dangerous_runs / runs
    if danger_prob >= sim.risk_prob.high:
        risk: Risk = "high"
    elif danger_prob >= sim.risk_prob.medium:
        risk = "medium"
    else:
        risk = "low"
    # samples[stat][day][run] -> paths[stat][run][day]
    paths = {stat: [list(run) for run in zip(*per_day)] for stat, per_day in samples.items()} if keep_paths else None
    return Forecast(start_day=start_day, runs=runs, bands=bands, danger_prob=danger_prob, risk=risk, paths=paths)
