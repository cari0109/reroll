from datetime import date

import pytest

from reroll import ops
from reroll.models import Repo
from reroll.narrator import MockNarrator, OptionDraft
from reroll.params import default_params
from reroll.storage import RepoCorrupt, RepoNotFound, load_repo, save_repo

PARAMS = default_params()


def new_repo() -> Repo:
    return ops.new_repo("test", PARAMS, date(2026, 10, 9))


def do_commit(repo: Repo, chosen: str = "a", decision: str | None = None):
    narrator = MockNarrator()
    ctx = ops.narrator_context(repo, PARAMS)
    proposal = narrator.propose(ctx, decision)
    options = ops.build_options(proposal.options, PARAMS, ops.rng_for(repo, proposal.decision))
    c = ops.commit(repo, proposal.decision, options, chosen, PARAMS)
    c.narration = narrator.narrate(ctx, c)
    return c


def test_empty_repo_defaults():
    repo = new_repo()
    assert ops.head(repo) is None
    assert ops.next_day(repo) == 1
    assert ops.current_state(repo) == PARAMS.initial_state
    assert ops.history(repo) == []


def test_commit_chain_moves_head_and_day():
    repo = new_repo()
    c1 = do_commit(repo)
    c2 = do_commit(repo, chosen="b")
    assert c1.parent is None and c2.parent == c1.id
    assert (c1.day, c2.day) == (1, 2)
    assert repo.branches["main"].head == c2.id
    assert [c.id for c in ops.history(repo)] == [c2.id, c1.id]
    assert ops.current_state(repo) == c2.state_after
    Repo.model_validate(repo.model_dump())  # integrity checks still pass


def test_commit_applies_chosen_effects_only():
    repo = new_repo()
    c = do_commit(repo, chosen="a")
    before = PARAMS.initial_state
    assert c.carryover == PARAMS.daily_drift  # day 1: no tags yet, only the daily drift
    for stat in c.chosen_option.effects.keys() | c.carryover.keys():
        expected = getattr(before, stat) + c.carryover.get(stat, 0) + c.chosen_option.effects.get(stat, 0)
        assert getattr(c.state_after, stat) == expected


def test_tags_from_yesterday_hit_today():
    repo = new_repo()
    day1 = do_commit(repo, decision="stay up gaming or sleep?", chosen="a")  # stay_up -> late_night
    assert day1.chosen_option.action == "stay_up"
    day2 = do_commit(repo)
    late_night = PARAMS.tags["late_night"].carryover["energy"]
    assert day2.carryover.get("energy", 0) == PARAMS.daily_drift["energy"] + late_night


def test_forecast_follows_head():
    repo = new_repo()
    assert ops.forecast(repo, PARAMS).start_day == 1
    do_commit(repo)
    f = ops.forecast(repo, PARAMS, days=3)
    assert f.start_day == 2 and f.days == 3


def test_effects_are_deterministic_for_same_history():
    a, b = do_commit(new_repo()), do_commit(new_repo())
    assert a.options == b.options and a.id == b.id


def test_build_options_rejects_unknown_action():
    with pytest.raises(ValueError, match="unknown action"):
        ops.build_options(
            [OptionDraft(label="x", action="fly"), OptionDraft(label="y", action="rest")],
            PARAMS,
            ops.rng_for(new_repo(), "d"),
        )


def test_mock_narrator_matches_keywords():
    p = MockNarrator().propose(ops.narrator_context(new_repo(), PARAMS), "要不要熬夜打游戏还是去健身")
    assert {o.action for o in p.options} == {"stay_up", "exercise"}


def test_mock_narrator_matches_english_keywords():
    p = MockNarrator().propose(ops.narrator_context(new_repo(), PARAMS), "Stay up gaming or hit the gym?")
    assert {o.action for o in p.options} == {"stay_up", "exercise"}


def test_mock_narrator_falls_back_when_nothing_matches():
    p = MockNarrator().propose(ops.narrator_context(new_repo(), PARAMS), "???")
    assert len(p.options) >= 2


def test_repo_language_drives_narration():
    zh = ops.new_repo("test", PARAMS, date(2026, 10, 9), lang="zh")
    c = do_commit(zh)
    assert c.decision == "今晚去健身还是加班？"
    assert "选手选择了" in c.narration and "精力" in c.narration

    en = do_commit(new_repo())
    assert en.decision == "Gym tonight, or stay late at work?"
    assert "the runner picks" in en.narration and "energy" in en.narration


def test_save_and_load_roundtrip(tmp_path):
    repo = new_repo()
    do_commit(repo)
    path = tmp_path / "life.json"
    save_repo(repo, path)
    assert load_repo(path) == repo
    assert not list(tmp_path.glob(".life-*"))  # temp file cleaned up


def test_load_missing_file(tmp_path):
    with pytest.raises(RepoNotFound):
        load_repo(tmp_path / "nope.json")


def test_load_corrupt_file(tmp_path):
    path = tmp_path / "life.json"
    path.write_text('{"meta": {}}')
    with pytest.raises(RepoCorrupt):
        load_repo(path)
