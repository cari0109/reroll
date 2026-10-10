import json
from datetime import date
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from reroll import ops
from reroll.claude_narrator import ClaudeNarrator, make_narrator
from reroll.narrator import MockNarrator
from reroll.params import default_params

PARAMS = default_params()


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        stop_reason, text = reply if isinstance(reply, tuple) else ("end_turn", reply)
        return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def fake_client(*replies):
    messages = FakeMessages(replies)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def ctx(lang="en"):
    return ops.narrator_context(ops.new_repo("t", PARAMS, date(2026, 10, 9), lang), PARAMS)


def proposal_json(*actions, decision="Late night snack?"):
    return json.dumps({"decision": decision, "options": [{"label": a.title(), "action": a} for a in actions]})


def api_error(cls, status):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=request), body=None)


def test_propose_parses_valid_output_and_sends_constraints():
    client, messages = fake_client(proposal_json("rest", "stay_up"))
    p = ClaudeNarrator(client=client).propose(ctx())
    assert p.decision == "Late night snack?"
    assert [o.action for o in p.options] == ["rest", "stay_up"]

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    schema = call["output_config"]["format"]["schema"]
    assert set(schema["properties"]["options"]["items"]["properties"]["action"]["enum"]) == set(PARAMS.actions)


def test_propose_keeps_user_decision_text():
    client, messages = fake_client(proposal_json("exercise", "rest", decision="something else"))
    p = ClaudeNarrator(client=client).propose(ctx(), "gym or nap?")
    assert p.decision == "gym or nap?"
    assert "gym or nap?" in messages.calls[0]["messages"][0]["content"]


def test_system_prompt_follows_repo_language():
    client, messages = fake_client(proposal_json("rest", "study"))
    ClaudeNarrator(client=client).propose(ctx("zh"))
    assert "Simplified Chinese" in messages.calls[0]["system"]


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        proposal_json("rest"),  # too few options
        proposal_json("rest", "rest"),  # duplicate action
        proposal_json("rest", "fly"),  # not in the action table
    ],
)
def test_invalid_output_is_retried_then_succeeds(bad):
    narrator = ClaudeNarrator(client=fake_client(bad, proposal_json("rest", "study"))[0])
    assert [o.action for o in narrator.propose(ctx()).options] == ["rest", "study"]
    assert narrator.last_fallback_reason is None


def test_falls_back_to_mock_after_repeated_invalid_output():
    client, messages = fake_client("nope", "still nope")
    narrator = ClaudeNarrator(client=client)
    p = narrator.propose(ctx())
    assert p == MockNarrator().propose(ctx())
    assert len(messages.calls) == 2
    assert narrator.last_fallback_reason.startswith("invalid output")


@pytest.mark.parametrize(
    "reply, reason",
    [
        (("refusal", ""), "declined"),
        (api_error(anthropic.AuthenticationError, 401), "authentication"),
        (api_error(anthropic.InternalServerError, 500), "API error 500"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "network"),
    ],
)
def test_api_problems_fall_back_without_retrying(reply, reason):
    client, messages = fake_client(reply)
    narrator = ClaudeNarrator(client=client)
    narrator.propose(ctx())
    assert len(messages.calls) == 1
    assert reason in narrator.last_fallback_reason


def test_truncated_output_is_retried():
    client, _ = fake_client(("max_tokens", '{"decision": "x", "opt'), proposal_json("rest", "study"))
    assert len(ClaudeNarrator(client=client).propose(ctx()).options) == 2


def test_narrate_includes_ghosts_and_returns_text():
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 9))
    before = ops.narrator_context(repo, PARAMS)
    p = MockNarrator().propose(before)
    options = ops.build_options(p.options, PARAMS, ops.rng_for(repo, p.decision))
    c = ops.commit(repo, p.decision, options, "a", PARAMS)

    client, messages = fake_client(json.dumps({"narration": "  GG, solid route.  "}))
    assert ClaudeNarrator(client=client).narrate(before, c) == "GG, solid route."
    prompt = messages.calls[0]["messages"][0]["content"]
    assert c.options[1].label in prompt  # the ghost option is part of the prompt


def test_narrate_rejects_empty_text():
    client, _ = fake_client(json.dumps({"narration": " "}), json.dumps({"narration": " "}))
    narrator = ClaudeNarrator(client=client)
    repo = ops.new_repo("t", PARAMS, date(2026, 10, 9))
    before = ops.narrator_context(repo, PARAMS)
    p = MockNarrator().propose(before)
    c = ops.commit(repo, p.decision, ops.build_options(p.options, PARAMS, ops.rng_for(repo, p.decision)), "a", PARAMS)
    assert narrator.narrate(before, c) == MockNarrator().narrate(before, c)


def test_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("REROLL_MODEL", "claude-haiku-5-5")
    client, messages = fake_client(proposal_json("rest", "study"))
    ClaudeNarrator(client=client).propose(ctx())
    assert messages.calls[0]["model"] == "claude-haiku-5-5"


def test_make_narrator_modes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.config/anthropic profile
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("REROLL_NARRATOR", "auto")
    assert isinstance(make_narrator(), MockNarrator)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(make_narrator(), ClaudeNarrator)
    monkeypatch.setenv("REROLL_NARRATOR", "mock")
    assert isinstance(make_narrator(), MockNarrator)
