"""Rules layer: every numeric change happens here. The narrator cannot touch state.

All functions are pure; randomness comes from the rng passed in, so results
are testable and reproducible.
"""

from __future__ import annotations

import random

from reroll.models import STAT_NAMES, Risk, StatBounds, StatName, State, Tag
from reroll.params import ActionSpec

Schema = dict[StatName, StatBounds]

# Risk thresholds: if any "survival" stat drops below a threshold, that risk
# level applies (assumed values). `goal` is a progress stat - being low on it
# isn't dangerous, so it's excluded.
RISK_STATS: tuple[StatName, ...] = ("energy", "mood", "money", "social")
HIGH_RISK_BELOW = 20
MEDIUM_RISK_BELOW = 35


def roll_effects(action: ActionSpec, rng: random.Random) -> dict[StatName, int]:
    """Roll concrete values within the ranges given by the action table."""
    return {stat: rng.randint(lo, hi) for stat, (lo, hi) in action.effects.items()}


def clamp_effects(effects: dict[StatName, int], schema: Schema) -> dict[StatName, int]:
    """Clamp each change to within ±max_delta."""
    out: dict[StatName, int] = {}
    for stat, delta in effects.items():
        limit = schema[stat].max_delta
        out[stat] = max(-limit, min(limit, delta))
    return out


def apply_effects(state: State, effects: dict[StatName, int], schema: Schema) -> State:
    """Apply changes and keep every stat within its [min, max]."""
    effects = clamp_effects(effects, schema)
    values = state.model_dump()
    for stat in STAT_NAMES:
        b = schema[stat]
        values[stat] = max(b.min, min(b.max, values[stat] + effects.get(stat, 0)))
    return State(**values)


def expire_tags(tags: list[Tag], day: int) -> list[Tag]:
    """Drop tags that have expired on or before `day`."""
    return [t for t in tags if t.expires_day > day]


def update_tags(tags: list[Tag], action: ActionSpec, day: int) -> list[Tag]:
    """Expire old tags, then attach the tags this action brings.

    If a tag with the same name is still active, bump its count and extend it
    (e.g. consecutive late nights); otherwise create a new one.
    """
    result = [t.model_copy() for t in expire_tags(tags, day)]
    by_name = {t.name: t for t in result}
    for spec in action.tags:
        existing = by_name.get(spec.name)
        if existing:
            existing.count += 1
            existing.expires_day = day + spec.duration
        else:
            tag = Tag(name=spec.name, since_day=day, expires_day=day + spec.duration)
            result.append(tag)
            by_name[spec.name] = tag
    return result


def assess_risk(state: State) -> Risk:
    lowest = min(getattr(state, s) for s in RISK_STATS)
    if lowest < HIGH_RISK_BELOW:
        return "high"
    if lowest < MEDIUM_RISK_BELOW:
        return "medium"
    return "low"
