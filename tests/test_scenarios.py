from datetime import date

from reroll import ops, scenarios
from reroll.i18n import LANGS
from reroll.models import State, Tag
from reroll.narrator import MockNarrator
from reroll.params import default_params

PARAMS = default_params()


def ctx(day=5, recent=(), tags=(), **stats):
    base = ops.narrator_context(ops.new_repo("t", PARAMS, date(2026, 10, 19)), PARAMS)
    state = State(**{"energy": 60, "mood": 60, "money": 60, "social": 60, "goal": 40, **stats})
    return base.model_copy(update={"day": day, "state": state, "recent": list(recent), "tags": list(tags)})


def share(c, question_en, n=400):
    """How often a scenario is picked across many slightly different situations."""
    hits = 0
    for i in range(n):
        cc = c.model_copy(update={"recent": [*c.recent, f"noise {i}"]})
        hits += scenarios.pick(cc).question.en == question_en
    return hits / n


def test_every_scenario_is_bilingual_and_uses_known_actions():
    for sc in scenarios.SCENARIOS:
        assert all(sc.question.get(lang) for lang in LANGS)
        assert 2 <= len(sc.options) <= 4
        assert all(action in PARAMS.actions for _, action in sc.options)


def test_day_one_is_always_the_classic():
    assert scenarios.pick(ctx(day=1)) is scenarios.SCENARIOS[0]


def test_pick_is_deterministic():
    assert scenarios.pick(ctx()) is scenarios.pick(ctx())


def test_low_energy_brings_up_exhaustion():
    q = "You're running on fumes"
    assert share(ctx(energy=15), q) > 5 * share(ctx(energy=80), q)
    assert share(ctx(energy=80), q) < 0.02  # it states the condition, so it rarely shows when untrue


def test_late_night_streak_gets_called_out():
    q = "Another late night in a row. Tonight too?"
    streak = [Tag(name="late_night", count=2, since_day=3, expires_day=8)]
    assert share(ctx(tags=streak), q) > 5 * share(ctx(), q)


def test_recent_questions_are_avoided():
    q = scenarios.SCENARIOS[4].question
    seen = [f"Day 4: {q.en} \u2192 x"]
    assert share(ctx(recent=seen), q.en) < share(ctx(), q.en) / 5


def test_two_weeks_rarely_repeat():
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 19))
    narrator, asked = MockNarrator(), []
    for _ in range(14):
        c = ops.narrator_context(repo, PARAMS)
        p = narrator.propose(c)
        asked.append(p.decision)
        ops.commit(repo, p.decision, ops.build_options(p.options, PARAMS, ops.rng_for(repo, p.decision)), "a", PARAMS)
    assert len(set(asked)) >= 11
