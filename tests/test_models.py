from datetime import date

import pytest
from pydantic import ValidationError

from lifegit.models import Branch, Commit, Meta, Option, Repo, State
from lifegit.params import default_params


def make_state(**kw) -> State:
    return State(**{"energy": 70, "mood": 60, "money": 50, "social": 50, "goal": 10, **kw})


def make_commit(**kw) -> Commit:
    data = {
        "id": "a1b2c3d",
        "parent": None,
        "branch": "main",
        "day": 1,
        "decision": "今晚去健身还是加班？",
        "options": [
            Option(id="a", label="去健身", action="exercise", effects={"energy": -5}),
            Option(id="b", label="加班", action="overtime", effects={"money": 5}),
        ],
        "chosen": "a",
        "state_after": make_state(energy=65),
    }
    return Commit(**{**data, **kw})


def make_repo(**kw) -> Repo:
    p = default_params()
    data = {
        "meta": Meta(name="my-life", created_at=date(2026, 10, 9)),
        "state_schema": p.stats,
        "initial_state": p.initial_state,
    }
    return Repo(**{**data, **kw})


def test_default_params_load():
    p = default_params()
    assert {"exercise", "overtime", "stay_up", "rest"} <= set(p.actions)


def test_commit_chosen_must_be_an_option():
    with pytest.raises(ValidationError, match="chosen"):
        make_commit(chosen="z")


def test_commit_needs_at_least_two_options():
    with pytest.raises(ValidationError):
        make_commit(options=[Option(id="a", label="x", action="rest")])


def test_commit_id_is_short_hash():
    with pytest.raises(ValidationError):
        make_commit(id="c3")


def test_empty_repo_is_valid():
    repo = make_repo()
    assert repo.current_branch == "main"
    assert repo.branches["main"].head is None


def test_repo_roundtrip_json():
    c = make_commit()
    repo = make_repo(commits=[c], branches={"main": Branch(head=c.id)})
    restored = Repo.model_validate_json(repo.model_dump_json())
    assert restored == repo
    assert restored.get_commit(c.id).chosen_option.label == "去健身"


def test_repo_rejects_dangling_branch_head():
    with pytest.raises(ValidationError, match="unknown commit"):
        make_repo(branches={"main": Branch(head="deadbee")})


def test_repo_rejects_unknown_parent():
    with pytest.raises(ValidationError, match="unknown parent"):
        make_repo(commits=[make_commit(parent="deadbee")])
