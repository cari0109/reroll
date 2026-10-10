from datetime import date

import pytest
from typer.testing import CliRunner

from reroll import ops
from reroll.cli import app
from reroll.models import Repo
from reroll.narrator import MockNarrator
from reroll.params import default_params
from reroll.storage import load_repo

PARAMS = default_params()
runner = CliRunner()


def new_repo() -> Repo:
    return ops.new_repo("test", PARAMS, date(2026, 10, 9))


def do_commit(repo: Repo, chosen: str = "a"):
    ctx = ops.narrator_context(repo, PARAMS)
    p = MockNarrator().propose(ctx)
    options = ops.build_options(p.options, PARAMS, ops.rng_for(repo, p.decision))
    return ops.commit(repo, p.decision, options, chosen, PARAMS)


def replay(repo: Repo, target, choice: str, name: str | None = None):
    ops.whatif_option(target, choice)
    ops.fork_before(repo, target, name)
    return ops.commit(repo, target.decision, target.options, choice, PARAMS)


def test_whatif_replays_ghost_exactly():
    repo = new_repo()
    c1 = do_commit(repo)
    c2 = do_commit(repo, chosen="a")
    do_commit(repo)

    alt = replay(repo, c2, "b")
    assert repo.current_branch == f"whatif/{c2.id}"
    assert alt.parent == c1.id and alt.day == c2.day
    assert alt.decision == c2.decision and alt.options == c2.options
    assert alt.chosen_option == next(o for o in c2.options if o.id == "b")
    Repo.model_validate(repo.model_dump())


def test_whatif_on_first_commit_forks_from_root():
    repo = new_repo()
    c1 = do_commit(repo)
    alt = replay(repo, c1, "b")
    assert alt.parent is None and alt.day == 1


def test_whatif_rejects_same_choice_and_unknown_option():
    repo = new_repo()
    c1 = do_commit(repo, chosen="a")
    with pytest.raises(ops.OpError) as e:
        ops.whatif_option(c1, "a")
    assert e.value.key == "err.whatif_same"
    with pytest.raises(ops.OpError) as e:
        ops.whatif_option(c1, "z")
    assert e.value.key == "commit.bad_choice"


def test_whatif_branch_names_dont_collide():
    repo = new_repo()
    c1 = do_commit(repo)
    replay(repo, c1, "b")
    assert ops.fork_before(repo, c1) == f"whatif/{c1.id}-2"


def test_whatif_custom_name_validated():
    repo = new_repo()
    c1 = do_commit(repo)
    with pytest.raises(ops.OpError):
        ops.fork_before(repo, c1, "main")


# ---------------------------------------------------------------- cli


def run(path, *args, input=None):
    return runner.invoke(app, ["--file", str(path), *args], input=input)


def test_cli_whatif_two_options_needs_no_prompt(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    run(path, "commit", "-c", "a")
    target = load_repo(path).commits[0]

    r = run(path, "whatif", target.id[:5])
    assert r.exit_code == 0, r.output
    assert "What if" in r.output

    repo = load_repo(path)
    assert repo.current_branch == f"whatif/{target.id}"
    assert ops.head(repo).chosen == "b"


def test_cli_whatif_prompts_among_ghosts(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    for _ in range(3):  # Day 3's scenario has three options
        run(path, "commit", "-c", "a")
    day3 = ops.head(load_repo(path))
    assert len(day3.options) == 3

    r = run(path, "whatif", "main", input="c\n")
    assert r.exit_code == 0, r.output
    assert ops.head(load_repo(path)).chosen == "c"


def test_cli_whatif_errors_leave_repo_untouched(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    run(path, "commit", "-c", "a")
    before = path.read_text()
    assert run(path, "whatif", "main", "-c", "a").exit_code == 1
    assert run(path, "whatif", "nope").exit_code == 1
    assert path.read_text() == before
