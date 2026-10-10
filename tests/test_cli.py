from typer.testing import CliRunner

from reroll.cli import app
from reroll.storage import load_repo

runner = CliRunner()


def run(path, *args, input=None):
    return runner.invoke(app, ["--file", str(path), *args], input=input)


def test_full_loop(tmp_path):
    path = tmp_path / "life.json"
    assert run(path, "init").exit_code == 0
    assert run(path, "init").exit_code == 1  # never overwrite an existing repo

    r = run(path, "commit", "--choose", "a")
    assert r.exit_code == 0, r.output
    r = run(path, "commit", "要不要熬夜追剧", input="b\n")
    assert r.exit_code == 0, r.output

    repo = load_repo(path)
    assert len(repo.commits) == 2

    r = run(path, "log")
    assert r.exit_code == 0
    assert "HEAD -> main" in r.output and "ghost" in r.output

    r = run(path, "status")
    assert r.exit_code == 0 and "Day 3" in r.output


def test_chinese_repo(tmp_path):
    path = tmp_path / "life.json"
    r = run(path, "init", "--lang", "zh")
    assert r.exit_code == 0 and "仅供娱乐" in r.output
    assert load_repo(path).meta.lang == "zh"

    r = run(path, "commit", "-c", "a")
    assert r.exit_code == 0 and "今晚去健身还是加班" in r.output and "精力" in r.output
    assert "幽灵" in run(path, "log").output
    assert "活跃标签" in run(path, "status").output


def test_invalid_language(tmp_path):
    assert run(tmp_path / "life.json", "init", "--lang", "fr").exit_code != 0


def test_commit_invalid_choice(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "commit", "--choose", "z")
    assert r.exit_code == 1
    assert load_repo(path).commits == []


def test_commands_without_repo(tmp_path):
    r = run(tmp_path / "life.json", "status")
    assert r.exit_code == 1 and "life init" in r.output


def test_forecast_and_status_show_outlook(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    run(path, "commit", "-c", "a")

    r = run(path, "forecast")
    assert r.exit_code == 0, r.output
    assert "simulated futures" in r.output and "risk:" in r.output

    r = run(path, "forecast", "--days", "30")
    assert r.exit_code == 0 and "30 days ahead" in r.output
    assert run(path, "forecast", "--days", "0").exit_code != 0

    r = run(path, "status")
    assert "in 7d:" in r.output and "chance" in r.output


def test_commit_explains_start_of_day(tmp_path):
    path = tmp_path / "life.json"
    run(path, "init")
    r = run(path, "commit", "-c", "a")
    assert "New day" in r.output and "% chance" in r.output
    assert "New day" in run(path, "log").output
