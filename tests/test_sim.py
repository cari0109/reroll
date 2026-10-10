from collections import Counter

from reroll import sim
from reroll.models import STAT_NAMES, State, Tag
from reroll.params import default_params

PARAMS = default_params()


def state(**kw) -> State:
    return State(**{"energy": 60, "mood": 60, "money": 60, "social": 60, "goal": 30, **kw})


def run(s: State, tags=(), history=None, **kw) -> sim.Forecast:
    return sim.forecast(s, list(tags), 1, history or Counter(), PARAMS, **kw)


def test_forecast_is_deterministic_and_shaped():
    a, b = run(state()), run(state())
    assert a == b
    assert a.days == PARAMS.simulation.horizon and a.runs == PARAMS.simulation.runs
    for stat in STAT_NAMES:
        for band in a.bands[stat]:
            assert band.p10 <= band.p25 <= band.p50 <= band.p75 <= band.p90


def test_custom_horizon():
    f = run(state(), days=30, runs=50)
    assert f.days == 30 and f.runs == 50


def test_low_stats_raise_risk():
    assert run(state()).risk == "low"
    assert run(state(energy=22, money=22)).risk == "high"
    assert run(state(energy=5)).danger_prob == 1.0  # already in danger


def test_low_energy_makes_rest_likely():
    w = sim.action_weights(state(energy=10), [], Counter(), PARAMS)
    assert w["rest"] == max(w.values())


def test_habits_from_history_and_tags():
    base = sim.action_weights(state(), [], Counter(), PARAMS)
    from_history = sim.action_weights(state(), [], Counter({"study": 4}), PARAMS)
    assert from_history["study"] > base["study"]

    late = [Tag(name="late_night", count=1, since_day=1, expires_day=4)]
    assert sim.action_weights(state(), late, Counter(), PARAMS)["stay_up"] > base["stay_up"]


def test_late_night_streak_drags_energy_down():
    streak = [Tag(name="late_night", count=3, since_day=1, expires_day=4)]
    assert run(state(), streak).at("energy", 3).p50 < run(state()).at("energy", 3).p50
