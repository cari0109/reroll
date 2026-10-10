from datetime import date

import pytest
from typer.testing import CliRunner

from reroll import graph, ops
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


# ---------------------------------------------------------------- ops


def test_branch_from_old_commit_rewinds_time():
    repo = new_repo()
    c1, c2, _ = do_commit(repo), do_commit(repo), do_commit(repo)
    ops.create_branch(repo, "what-if", c1.id)
    ops.checkout(repo, "what-if")

    assert ops.next_day(repo) == 2
    assert ops.current_state(repo) == c1.state_after
    alt = do_commit(repo, chosen="b")
    assert alt.parent == c1.id and alt.branch == "what-if" and alt.day == 2
    assert repo.branches["main"].head != alt.id  # main is untouched
    Repo.model_validate(repo.model_dump())


def test_same_point_same_physics():
    """Taking the ghost option on a new branch yields exactly the ghost's numbers."""
    repo = new_repo()
    c1 = do_commit(repo)
    c2 = do_commit(repo, chosen="a")
    ops.create_branch(repo, "alt", c1.id)
    ops.checkout(repo, "alt")
    alt = do_commit(repo, chosen="b")
    assert alt.chosen_option == next(o for o in c2.options if o.id == "b")


def test_branch_defaults_to_head_and_works_on_empty_repo():
    repo = new_repo()
    assert ops.create_branch(repo, "early").head is None
    c1 = do_commit(repo)
    assert ops.create_branch(repo, "later").head == c1.id


def test_resolve_ref():
    repo = new_repo()
    c1 = do_commit(repo)
    assert ops.resolve_ref(repo, "main") == c1.id
    assert ops.resolve_ref(repo, c1.id[:4]) == c1.id
    assert ops.resolve_ref(repo, c1.id[:4].upper()) == c1.id
    with pytest.raises(ops.OpError) as e:
        ops.resolve_ref(repo, c1.id[:3])  # too short to be a prefix
    assert e.value.key == "err.ref_unknown"


@pytest.mark.parametrize(
    "name, key",
    [("main", "err.branch_exists"), ("has space", "err.branch_name"), ("-x", "err.branch_name")],
)
def test_create_branch_errors(name, key):
    with pytest.raises(ops.OpError) as e:
        ops.create_branch(new_repo(), name)
    assert e.value.key == key


def test_unicode_branch_name():
    repo = new_repo()
    ops.create_branch(repo, "如果当初")
    assert "如果当初" in repo.branches


def test_checkout_unknown_branch():
    with pytest.raises(ops.OpError):
        ops.checkout(new_repo(), "nope")


# ---------------------------------------------------------------- graph


def test_graph_linear():
    repo = new_repo()
    for _ in range(3):
        do_commit(repo)
    assert [r.prefix for r in graph.layout(ops.commits_newest_first(repo))] == ["*", "*", "*"]


def test_graph_fork():
    repo = new_repo()
    c1 = do_commit(repo)
    do_commit(repo)
    ops.create_branch(repo, "alt", c1.id)
    ops.checkout(repo, "alt")
    do_commit(repo, chosen="b")

    rows = graph.layout(ops.commits_newest_first(repo))
    assert [r.prefix for r in rows] == ["*", "│ *", "├─┘", "*"]
    assert rows[-1].commit.id == c1.id


def test_graph_three_way_fork_with_crossing():
    repo = new_repo()
    c1 = do_commit(repo)
    do_commit(repo)
    do_commit(repo)
    for name in ("x", "y"):
        ops.create_branch(repo, name, c1.id)
        ops.checkout(repo, name)
        do_commit(repo, chosen="b")

    rows = graph.layout(ops.commits_newest_first(repo))
    assert rows[-2].prefix == "├─┴─┘" and rows[-1].commit.id == c1.id
    commits = [r.commit for r in rows if r.commit]
    assert len(commits) == len(repo.commits)  # every commit drawn exactly once


# ---------------------------------------------------------------- cli


def run(path, *args):
    return runner.invoke(app, ["--file", str(path), *args])


def test_cli_branch_checkout_graph(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    for _ in range(3):
        run(path, "commit", "-c", "a")
    first = load_repo(path).commits[0].id

    r = run(path, "checkout", "-b", "what-if", first[:5])
    assert r.exit_code == 0, r.output
    assert "Day 1" in r.output and "Day 2" in r.output  # rewind message
    assert run(path, "commit", "-c", "b").exit_code == 0

    r = run(path, "branch")
    assert "* " in r.output and "what-if" in r.output and "main" in r.output

    r = run(path, "log", "--graph")
    assert r.exit_code == 0, r.output
    assert "HEAD -> what-if" in r.output and "├─┘" in r.output

    r = run(path, "log")
    assert "HEAD -> what-if" in r.output and r.output.count("* ") == 2

    assert "Already on" in run(path, "checkout", "what-if").output
    assert run(path, "checkout", "main").exit_code == 0
    assert load_repo(path).current_branch == "main"


def test_cli_branch_errors(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "branch", "main")
    assert r.exit_code == 1 and "already exists" in r.output
    assert run(path, "checkout", "nope").exit_code == 1
    assert run(path, "checkout", "main", "abcd").exit_code != 0  # START needs -b


def test_cli_escapes_markup_in_user_text(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "commit", "[bold]sleep[/bold] or [red]game[/red]?", "-c", "a")
    assert r.exit_code == 0, r.output
    assert "[bold]sleep[/bold]" in run(path, "log").output
