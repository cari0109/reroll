import random

from reroll import rules
from reroll.models import State, Tag
from reroll.params import ActionSpec, default_params

SCHEMA = default_params().stats


def make_state(**kw) -> State:
    return State(**{"energy": 50, "mood": 50, "money": 50, "social": 50, "goal": 50, **kw})


def action(tags=(), **effects) -> ActionSpec:
    return ActionSpec(
        description={"en": "test", "zh": "测试"},
        effects={k: tuple(v) for k, v in effects.items()},
        tags=[{"name": n, "duration": d} for n, d in tags],
        source="test",
    )


def test_roll_effects_stays_in_range_and_is_reproducible():
    a = action(energy=(-8, -3), mood=(2, 6))
    first = rules.roll_effects(a, random.Random(42))
    assert first == rules.roll_effects(a, random.Random(42))
    for _ in range(100):
        e = rules.roll_effects(a, random.Random())
        assert -8 <= e["energy"] <= -3 and 2 <= e["mood"] <= 6


def test_clamp_effects_respects_max_delta():
    assert rules.clamp_effects({"energy": 99, "goal": -99}, SCHEMA) == {
        "energy": SCHEMA["energy"].max_delta,
        "goal": -SCHEMA["goal"].max_delta,
    }


def test_apply_effects_clamps_to_bounds():
    s = rules.apply_effects(make_state(energy=5, mood=98), {"energy": -10, "mood": 10}, SCHEMA)
    assert s.energy == 0 and s.mood == 100
    assert s.money == 50  # untouched stats stay the same


def test_update_tags_adds_new_tag():
    tags = rules.update_tags([], action(tags=[("late_night", 3)]), day=2)
    assert tags == [Tag(name="late_night", count=1, since_day=2, expires_day=5)]


def test_update_tags_stacks_active_tag():
    existing = [Tag(name="late_night", since_day=1, expires_day=4)]
    tags = rules.update_tags(existing, action(tags=[("late_night", 3)]), day=2)
    assert tags == [Tag(name="late_night", count=2, since_day=1, expires_day=5)]
    assert existing[0].count == 1  # input is not mutated


def test_update_tags_expires_old_and_restarts():
    existing = [Tag(name="late_night", count=3, since_day=1, expires_day=4)]
    tags = rules.update_tags(existing, action(tags=[("late_night", 3)]), day=4)
    assert tags == [Tag(name="late_night", count=1, since_day=4, expires_day=7)]


def test_carryover_scales_with_count():
    specs = default_params().tags
    tags = [Tag(name="late_night", count=2, since_day=1, expires_day=5), Tag(name="studied", since_day=1, expires_day=4)]
    assert rules.carryover(tags, specs) == {"energy": -6, "goal": 1}


def test_carryover_drops_zero_totals():
    specs = default_params().tags
    assert rules.carryover([Tag(name="frugal", since_day=1, expires_day=3)], specs) == {}


def test_start_day_expires_before_applying_carryover():
    tags = [
        Tag(name="late_night", count=1, since_day=1, expires_day=3),  # expires on day 3
        Tag(name="rested", count=1, since_day=2, expires_day=4),
    ]
    state, active, change = rules.start_day(make_state(), tags, day=3, params=default_params(), schema=SCHEMA)
    assert [t.name for t in active] == ["rested"]
    # daily drift (energy +3, mood -2, social -1) plus rested (energy +1)
    assert change == {"energy": 4, "mood": -2, "social": -1}
    assert (state.energy, state.mood, state.social) == (54, 48, 49)
