import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from reroll.cli import app as cli
from reroll.narrator import MockNarrator
from reroll.server import create_app
from reroll.storage import load_repo


@pytest.fixture
def life(tmp_path):
    path = tmp_path / "life.json"
    assert CliRunner().invoke(cli, ["--file", str(path), "init"]).exit_code == 0
    return path


@pytest.fixture
def client(life):
    return TestClient(create_app(life, narrator=MockNarrator()))


def test_state_shape(client):
    s = client.get("/api/state").json()
    assert s["today"] == 0 and s["branch"] == "main" and s["path"] == []
    assert len(s["decision"]["options"]) >= 2
    f = s["forecast"]
    assert len(f["paths"]["energy"]) == f["runs"] and len(f["paths"]["energy"][0]) == f["days"]
    assert set(s["option_forecasts"]) == {o["id"] for o in s["decision"]["options"]}


def test_todays_effects_stay_hidden_until_the_choice(client):
    s = client.get("/api/state").json()
    for o in s["decision"]["options"]:
        assert "effects" not in o and "state_if" not in o
    after = client.post("/api/commit", json={"option": "a"}).json()
    revealed = after["path"][-1]["options"]
    assert all("effects" in o and "state_if" in o for o in revealed)


def test_commit_matches_what_was_shown_and_persists(client, life):
    shown = client.get("/api/state").json()["decision"]
    after = client.post("/api/commit", json={"option": "b"}).json()
    c = after["path"][-1]
    assert c["decision"] == shown["question"] and c["chosen"] == "b"
    assert [o["label"] for o in c["options"]] == [o["label"] for o in shown["options"]]
    assert c["narration"]
    assert after["today"] == 1 and after["decision"]["day"] == 2
    assert load_repo(life).commits[0].id == c["id"]  # written to life.json


def test_bad_option(client):
    r = client.post("/api/commit", json={"option": "z"})
    assert r.status_code == 400 and "z" in r.json()["detail"]


def test_whatif_and_checkout(client):
    client.post("/api/commit", json={"option": "a"})
    day1 = client.post("/api/commit", json={"option": "a"}).json()["path"][0]

    s = client.post("/api/whatif", json={"commit": day1["id"], "option": "b"}).json()
    assert s["branch"] == f"whatif/{day1['id']}"
    assert s["path"][-1]["chosen"] == "b" and s["today"] == 1
    assert s["others"] and s["others"][0]["name"] == "main"  # main is now a parallel life
    ghost_b = next(o for o in day1["options"] if o["id"] == "b")
    assert s["path"][-1]["state"] == ghost_b["state_if"]  # rerolling lands exactly on the ghost

    s = client.post("/api/checkout", json={"branch": "main"}).json()
    assert s["branch"] == "main" and s["today"] == 2


def test_whatif_errors(client):
    c = client.post("/api/commit", json={"option": "a"}).json()["path"][0]
    assert client.post("/api/whatif", json={"commit": c["id"], "option": "a"}).status_code == 400
    assert client.post("/api/whatif", json={"commit": "zzzz", "option": "b"}).status_code == 400
    assert client.post("/api/checkout", json={"branch": "nope"}).status_code == 400


def test_cli_changes_show_up_in_the_browser(client, life):
    client.get("/api/state")
    CliRunner().invoke(cli, ["--file", str(life), "commit", "-c", "a"])
    assert client.get("/api/state").json()["today"] == 1


def test_serves_the_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Reroll Observatory" in r.text
    assert client.get("/app.js").status_code == 200


def test_missing_repo(tmp_path):
    r = TestClient(create_app(tmp_path / "nope.json", narrator=MockNarrator())).get("/api/state")
    assert r.status_code == 404
