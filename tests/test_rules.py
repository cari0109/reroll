import random

from lifegit import rules
from lifegit.models import State, Tag
from lifegit.params import ActionSpec, default_params

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


def test_assess_risk():
    assert rules.assess_risk(make_state()) == "low"
    assert rules.assess_risk(make_state(money=30)) == "medium"
    assert rules.assess_risk(make_state(energy=10)) == "high"
    assert rules.assess_risk(make_state(goal=0)) == "low"  # low progress isn't risky
