"""Narrator backed by the Claude API.

Claude only writes text and picks actions from the action table; the JSON it
returns is constrained by a schema (the `action` field is an enum of the table's
keys) and validated again with pydantic. On repeated validation failures, API
errors, or refusals we fall back to the offline MockNarrator, so a commit never
fails because of the narrator.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from reroll.models import Commit
from reroll.narrator import MockNarrator, Narrator, NarratorContext, Proposal, format_effects

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_ENV = "REROLL_MODEL"
NARRATOR_ENV = "REROLL_NARRATOR"  # auto (default) | claude | mock

# Short, creative text: low effort keeps latency and cost down.
EFFORT = "low"
MAX_TOKENS = 4000
MAX_ATTEMPTS = 2
FALLBACK_BETA = "server-side-fallback-2026-07-01"

LANG_NAMES = {"en": "English", "zh": "Simplified Chinese"}

SYSTEM_PROMPT = """\
You are the narrator of Reroll, a just-for-fun CLI that treats someone's life like a git repo: \
every small daily decision is a commit, and "what if" is a branch.

Your voice is a sarcastic but warm speedrun commentator: playful roasts, gaming metaphors, \
never mean-spirited.

Hard rules:
- You never decide numbers. A separate rules engine owns all stats; only use numbers you are given.
- Keep everything about small everyday choices (sleep, exercise, work, spending, friends, study, rest).
- Never give medical, financial, legal or safety advice, and never treat the simulation as a real \
prediction. If the user's decision touches those areas, keep it light and generic.
- Write all user-facing text in {language}.
"""

PROPOSE_TASK = """\
Propose today's decision point.

{decision_line}
"decision" is one short question (max ~15 words, or ~25 Chinese characters). No day number, no \
scene-setting preamble and no commentary: the commentary comes later, after the choice.

Write 2-4 options; usually 2-3, use 4 only when the decision naturally has that many. Each option needs:
- "label": a short, punchy choice (max ~6 words / ~12 Chinese characters), no numbers.
- "action": the action type from the table below that best matches the option. Use each action \
at most once.

Action table:
{actions}

Context (current state is 0-100 per stat; tags are recent history):
{context}
"""

NARRATE_TASK = """\
The player just committed a choice. Write the commentary for it: 1-2 short sentences, max ~30 words \
(or ~50 Chinese characters). React to the choice, the risk rating or a ghost option they skipped - \
pick what's funniest, don't list everything. The player already sees the stat table, so mention at \
most one stat change, and no other numbers.

Decision: {decision}
Chosen: {chosen} ({effects})
Ghost options not taken: {ghosts}
Risk rating: {risk}

Context before this choice:
{context}
"""

T = TypeVar("T")


class _Narration(BaseModel):
    narration: str


def proposal_schema(actions: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "action": {"type": "string", "enum": actions},
                    },
                    "required": ["label", "action"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["decision", "options"],
        "additionalProperties": False,
    }


NARRATION_SCHEMA = {
    "type": "object",
    "properties": {"narration": {"type": "string"}},
    "required": ["narration"],
    "additionalProperties": False,
}


def render_context(ctx: NarratorContext) -> str:
    return json.dumps(
        {
            "day": ctx.day,
            "state": ctx.state.model_dump(),
            "active_tags": [t.model_dump() for t in ctx.tags],
            "recent_history": ctx.recent,
        },
        ensure_ascii=False,
        indent=2,
    )


class ClaudeNarrator:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str | None = None,
        fallback: Narrator | None = None,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self.fallback = fallback or MockNarrator()
        self.last_fallback_reason: str | None = None

    def propose(self, ctx: NarratorContext, decision: str | None = None) -> Proposal:
        actions = "\n".join(f"- {name}: {desc}" for name, desc in ctx.actions.items())
        decision_line = (
            f"The player brought this decision; keep it as the decision text: {decision!r}"
            if decision
            else "Invent one small, relatable decision that fits their current state and recent history."
        )
        prompt = PROPOSE_TASK.format(decision_line=decision_line, actions=actions, context=render_context(ctx))

        def parse(text: str) -> Proposal:
            p = Proposal.model_validate_json(text)
            used = [o.action for o in p.options]
            unknown = set(used) - set(ctx.actions)
            if unknown:
                raise ValueError(f"unknown actions {sorted(unknown)}")
            if len(set(used)) != len(used):
                raise ValueError("duplicate actions")
            if decision:
                p.decision = decision
            return p

        return self._call(
            ctx, prompt, proposal_schema(list(ctx.actions)), parse, lambda: self.fallback.propose(ctx, decision)
        )

    def narrate(self, ctx: NarratorContext, commit: Commit) -> str:
        chosen = commit.chosen_option
        ghosts = [o for o in commit.options if o.id != commit.chosen]
        prompt = NARRATE_TASK.format(
            decision=commit.decision,
            chosen=chosen.label,
            effects=format_effects(chosen.effects, ctx.lang),
            ghosts="; ".join(f"{o.label} ({format_effects(o.effects, ctx.lang)})" for o in ghosts) or "-",
            risk=commit.risk,
            context=render_context(ctx),
        )

        def parse(text: str) -> str:
            narration = _Narration.model_validate_json(text).narration.strip()
            if not narration:
                raise ValueError("empty narration")
            return narration

        return self._call(ctx, prompt, NARRATION_SCHEMA, parse, lambda: self.fallback.narrate(ctx, commit))

    def _call(
        self,
        ctx: NarratorContext,
        prompt: str,
        schema: dict,
        parse: Callable[[str], T],
        fallback: Callable[[], T],
    ) -> T:
        """Call Claude, validate, retry on bad output; fall back to the offline narrator otherwise.

        Transport errors are not retried here: the SDK already retries 408/409/429/5xx
        and connection errors (max_retries=2).
        """
        self.last_fallback_reason = None
        reason = "unknown"
        for _ in range(MAX_ATTEMPTS):
            try:
                response = self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                    output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
                    system=SYSTEM_PROMPT.format(language=LANG_NAMES[ctx.lang]),
                    messages=[{"role": "user", "content": prompt}],
                )
            except anthropic.AuthenticationError:
                reason = "authentication failed (check ANTHROPIC_API_KEY)"
                break
            except anthropic.APIStatusError as e:
                reason = f"API error {e.status_code}"
                break
            except anthropic.APIConnectionError:
                reason = "network error"
                break

            if response.stop_reason == "refusal":
                reason = "the model declined"
                break
            if response.stop_reason == "max_tokens":
                reason = "response was cut off"
                continue
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                return parse(text)
            except (ValidationError, ValueError) as e:
                reason = f"invalid output: {e}".splitlines()[0]
                continue

        self.last_fallback_reason = reason
        return fallback()


def has_credentials() -> bool:
    """Best-effort check for Anthropic credentials (env vars or an `ant auth login` profile)."""
    if any(os.environ.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


def make_narrator() -> Narrator:
    """Pick a narrator from REROLL_NARRATOR (auto | claude | mock). `auto` uses
    Claude when credentials are available and the offline narrator otherwise."""
    mode = os.environ.get(NARRATOR_ENV, "auto").lower()
    if mode == "mock" or (mode == "auto" and not has_credentials()):
        return MockNarrator()
    return ClaudeNarrator()
