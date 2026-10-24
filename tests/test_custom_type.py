from datetime import date

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reroll import ops
from reroll.cli import app as cli
from reroll.narrator import MockNarrator, OptionDraft
from reroll.params import custom_action, default_params, parse_custom
from reroll.server import create_app
from reroll.storage import load_repo

PARAMS = default_params()
runner = CliRunner()


def test_custom_action_round_trip_and_spec():
    name = custom_action({"mood": "+", "energy": "-"})
    assert name == "custom:energy-,mood+"  # canonical order
    assert parse_custom(name) == {"energy": "-", "mood": "+"}
    spec = PARAMS.action(name)
    assert spec.effects == {"energy": PARAMS.custom_action.down, "mood": PARAMS.custom_action.up}
    assert spec.tags == []
    assert PARAMS.describe(name, "zh") == "自定义：精力↓ 心情↑"


@pytest.mark.parametrize("bad", ["custom:", "custom:joy+", "custom:mood*", "custom:mood+,mood-", "exercise+"])
def test_invalid_custom_actions(bad):
    assert not PARAMS.is_action(bad)
    with pytest.raises(KeyError):
        PARAMS.action(bad)


def test_commit_with_a_custom_option_follows_its_directions():
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 23))
    name = custom_action({"mood": "+", "energy": "-"})
    opts = ops.custom_options(repo, PARAMS, "Pet the cat for an hour?", [OptionDraft(label="Yes", action=name), OptionDraft(label="No", action="rest")])
    lo, hi = PARAMS.custom_action.up
    assert lo <= opts[0].effects["mood"] <= hi and opts[0].effects["energy"] < 0
    c = ops.commit(repo, "Pet the cat for an hour?", opts, "a", PARAMS)
    assert c.chosen_option.action == name
    # forecasts that start with a custom action work too
    assert ops.forecast(repo, PARAMS, first_action=name).days == PARAMS.simulation.horizon


def test_cli_custom_type(tmp_path):
    path = tmp_path / "life.json"
    runner.invoke(cli, ["--file", str(path), "init", "--lang", "zh"])
    r = runner.invoke(cli, ["--file", str(path), "commit", "撸猫一小时？", "-o", "撸:mood+,energy-", "-o", "不撸:rest", "-c", "a"])
    assert r.exit_code == 0, r.output
    assert "自定义：精力↓ 心情↑" in r.output
    assert load_repo(path).commits[0].options[0].action == "custom:energy-,mood+"


def test_api_custom_type(tmp_path):
    path = tmp_path / "life.json"
    runner.invoke(cli, ["--file", str(path), "init"])
    c = TestClient(create_app(path, narrator=MockNarrator()))
    body = {"question": "Pet the cat?", "options": [{"label": "Yes", "action": "custom:mood+,social+"}, {"label": "No", "action": "rest"}]}
    d = c.post("/api/decision", json=body).json()["decision"]
    assert d["options"][0]["hint"] == "Custom: mood↑ social↑"
    s = c.post("/api/commit", json={"option": "a"}).json()
    effects = s["path"][-1]["options"][0]["effects"]
    assert set(effects) == {"mood", "social"} and all(v > 0 for v in effects.values())
    bad = {"question": "q", "options": [{"label": "x", "action": "custom:joy+"}, {"label": "y", "action": "rest"}]}
    assert c.post("/api/decision", json=bad).status_code == 400
