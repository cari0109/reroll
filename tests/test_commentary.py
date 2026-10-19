from datetime import date

from reroll import ops
from reroll.commentary import commentary
from reroll.models import State
from reroll.narrator import OptionDraft
from reroll.params import default_params

PARAMS = default_params()


def life(lang="en", **start):
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 19), lang)
    if start:
        repo.initial_state = State(**{**repo.initial_state.model_dump(), **start})
    return repo


def choose(repo, first: str, second: str, pick="a"):
    """Commit a two-option day where option a is `first` and option b is `second`; return the commentary."""
    ctx = ops.narrator_context(repo, PARAMS)
    drafts = [OptionDraft(label=first.title(), action=first), OptionDraft(label=second.title(), action=second)]
    c = ops.commit(repo, f"day {ctx.day}", ops.custom_options(repo, PARAMS, f"day {ctx.day}", drafts), pick, PARAMS)
    return commentary(ctx, c)


def test_opens_with_the_choice_and_ends_with_a_quip():
    text = choose(life(), "exercise", "overtime")
    assert text.startswith("Day 1: the runner picks “Exercise”.")
    assert text.count(".") >= 3


def test_calls_out_a_streak():
    repo = life()
    for _ in range(2):
        choose(repo, "stay_up", "study")
    text = choose(repo, "stay_up", "study")
    assert "3 late nights" in text or "Night 3" in text


def test_calls_out_a_stat_in_the_red():
    text = choose(life(energy=14), "overtime", "stay_up")
    assert "Energy is down to" in text or "Energy at" in text


def test_compares_with_the_ghost_that_would_have_helped():
    text = choose(life(energy=38), "stay_up", "rest")
    assert "Rest" in text and "energy at" in text and ", not " in text


def test_is_deterministic_and_bilingual():
    a, b = choose(life(), "exercise", "overtime"), choose(life(), "exercise", "overtime")
    assert a == b
    zh = choose(life("zh"), "exercise", "overtime")
    assert zh.startswith("Day 1，选手选择了「") and "runner" not in zh
