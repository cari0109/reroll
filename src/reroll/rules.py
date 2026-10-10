"""Rules layer: every numeric change happens here. The narrator cannot touch state.

All functions are pure; randomness comes from the rng passed in, so results
are testable and reproducible.
"""

from __future__ import annotations

import random

from reroll.models import STAT_NAMES, StatBounds, StatName, State, Tag
from reroll.params import ActionSpec, Params, TagEffects

Schema = dict[StatName, StatBounds]


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


def carryover(tags: list[Tag], specs: dict[str, TagEffects]) -> dict[StatName, int]:
    """Daily aftershock of active tags, scaled by each tag's count. Independent of today's choice."""
    total: dict[StatName, int] = {}
    for tag in tags:
        for stat, delta in specs[tag.name].carryover.items():
            total[stat] = total.get(stat, 0) + delta * tag.count
    return {stat: v for stat, v in total.items() if v}


def start_day(
    state: State, tags: list[Tag], day: int, params: Params, schema: Schema
) -> tuple[State, list[Tag], dict[StatName, int]]:
    """Begin `day`: expire old tags, then apply the daily drift plus the aftershock of
    the remaining tags. Returns the new state, the active tags, and the change applied.

    Shared by real commits and the simulation so both follow the same physics.
    """
    active = expire_tags(tags, day)
    change = dict(params.daily_drift)
    for stat, delta in carryover(active, params.tags).items():
        change[stat] = change.get(stat, 0) + delta
    change = {k: v for k, v in clamp_effects(change, schema).items() if v}
    return apply_effects(state, change, schema), active, change
