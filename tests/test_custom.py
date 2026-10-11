import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reroll import ops
from reroll.claude_narrator import ClaudeNarrator
from reroll.cli import app as cli
from reroll.narrator import MockNarrator, OptionDraft
from reroll.params import default_params
from reroll.server import create_app
from reroll.storage import load_repo

PARAMS = default_params()
runner = CliRunner()


def ctx():
    return ops.narrator_context(ops.new_repo("t", PARAMS, date(2026, 10, 11)), PARAMS)


# ---------------------------------------------------------------- classification


@pytest.mark.parametrize(
    "label, action",
    [("去爬山", "exercise"), ("在家打游戏", "stay_up"), ("约朋友吃饭", "socialize"), ("cook dinner", "save_money"),
     ("practice piano", "study"), ("早点睡", "rest"), ("看电影", None)],
)
def test_mock_classify(label, action):
    assert MockNarrator().classify(ctx(), "q", [label]) == [action]


@pytest.mark.parametrize(
    "spec, expected",
    [("Go hiking:exercise", ("Go hiking", "exercise")), ("6:30 run", ("6:30 run", None)),
     ("nap:snooze", ("nap:snooze", None)), ("  rest  ", ("rest", None))],
)
def test_parse_option_spec(spec, expected):
    assert ops.parse_option_spec(spec, PARAMS.actions) == expected


def test_custom_options_validation():
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 11))
    one = [OptionDraft(label="x", action="rest")]
    with pytest.raises(ops.OpError) as e:
        ops.custom_options(repo, PARAMS, "q", one)
    assert e.value.key == "custom.count"
    with pytest.raises(ops.OpError) as e:
        ops.custom_options(repo, PARAMS, " ", one * 2)
    assert e.value.key == "custom.need_question"
    opts = ops.custom_options(repo, PARAMS, "q", [OptionDraft(label="a", action="rest")] * 2)
    assert [o.action for o in opts] == ["rest", "rest"]  # same type twice is allowed


def fake_claude(*texts):
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=texts[len(calls) - 1])])

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), calls


def test_claude_classify_and_fallback():
    client, calls = fake_claude(json.dumps({"actions": ["exercise", "rest"]}))
    assert ClaudeNarrator(client=client).classify(ctx(), "q", ["hike", "nap"]) == ["exercise", "rest"]
    schema = calls[0]["output_config"]["format"]["schema"]
    assert set(schema["properties"]["actions"]["items"]["enum"]) == set(PARAMS.actions)

    # wrong length twice -> keyword fallback
    client, _ = fake_claude(json.dumps({"actions": ["rest"]}), json.dumps({"actions": ["rest"]}))
    narrator = ClaudeNarrator(client=client)
    assert narrator.classify(ctx(), "q", ["去爬山", "看电影"]) == ["exercise", None]
    assert narrator.last_fallback_reason.startswith("invalid output")


# ---------------------------------------------------------------- cli


def run(path, *args, input=None):
    return runner.invoke(cli, ["--file", str(path), *args], input=input)


def test_cli_own_options_with_guesses(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "commit", "Weekend plans?", "-o", "Go hiking", "-o", "Game all day", "-c", "a")
    assert r.exit_code == 0, r.output
    assert "guessed" in r.output
    c = load_repo(path).commits[0]
    assert c.decision == "Weekend plans?"
    assert [(o.label, o.action) for o in c.options] == [("Go hiking", "exercise"), ("Game all day", "stay_up")]


def test_cli_explicit_type_and_unknown_label(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "commit", "Tonight?", "-o", "Watch a movie", "-o", "Sleep early", "-c", "a")
    assert r.exit_code == 1 and "Watch a movie" in r.output and "rest" in r.output
    r = run(path, "commit", "Tonight?", "-o", "Watch a movie:rest", "-o", "Sleep early", "-c", "a")
    assert r.exit_code == 0, r.output
    assert load_repo(path).commits[0].options[0].action == "rest"


def test_cli_own_options_need_question_and_count(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    assert run(path, "commit", "-o", "a:rest", "-o", "b:rest", "-c", "a").exit_code == 1
    assert run(path, "commit", "q", "-o", "a:rest", "-c", "a").exit_code == 1
    assert load_repo(path).commits == []


def test_cli_interactive_correction(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    # unknown label -> asked; guessed label -> confirm "n" -> corrected; then choose b
    r = run(path, "commit", "Tonight?", "-o", "Watch a movie", "-o", "Go for a run", input="rest\nn\nstudy\nb\n")
    assert r.exit_code == 0, r.output
    c = load_repo(path).commits[0]
    assert [o.action for o in c.options] == ["rest", "study"] and c.chosen == "b"


# ---------------------------------------------------------------- server


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    return TestClient(create_app(path, narrator=MockNarrator())), path


def test_api_own_decision_flow(client):
    c, path = client
    body = {"question": "Weekend plans?", "options": [{"label": "Go hiking"}, {"label": "Watch a movie", "action": "rest"}]}
    s = c.post("/api/decision", json=body).json()
    d = s["decision"]
    assert d["custom"] and d["question"] == "Weekend plans?"
    assert [(o["action"], o["guessed"]) for o in d["options"]] == [("exercise", True), ("rest", False)]
    assert all("effects" not in o for o in d["options"])  # still hidden before the choice
    assert set(s["option_forecasts"]) == {"a", "b"}

    after = c.post("/api/commit", json={"option": "b"}).json()
    assert after["path"][-1]["decision"] == "Weekend plans?"
    assert not after["decision"]["custom"]  # the next day is a fresh prompt
    assert load_repo(path).commits[0].options[1].label == "Watch a movie"


def test_api_own_decision_errors_and_reset(client):
    c, _ = client
    original = c.get("/api/state").json()["decision"]["question"]
    r = c.post("/api/decision", json={"question": "q", "options": [{"label": "Watch a movie"}, {"label": "nap"}]})
    assert r.status_code == 400 and "Watch a movie" in r.json()["detail"]
    r = c.post("/api/decision", json={"question": "q", "options": [{"label": "x", "action": "fly"}, {"label": "nap"}]})
    assert r.status_code == 400 and "fly" in r.json()["detail"]
    assert c.post("/api/decision", json={"question": "q", "options": [{"label": "nap"}]}).status_code == 422

    c.post("/api/decision", json={"question": "Mine", "options": [{"label": "nap"}, {"label": "run"}]})
    assert c.post("/api/decision/reset", json={}).json()["decision"]["question"] == original
