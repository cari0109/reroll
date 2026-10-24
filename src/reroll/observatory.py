"""The Observatory: everything the web UI needs, as plain JSON-able dicts.

Transport-agnostic on purpose: `server.py` serves it over HTTP for `life serve`, and the
GitHub Pages demo runs this same module in the browser via Pyodide. life.json stays the
single source of truth. The effects of today's options are never included before the
choice; they are revealed only after the commit ("collapse").
"""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from reroll import ops, rules
from reroll.i18n import t
from reroll.models import STAT_NAMES, Commit, Option, Repo
from reroll.narrator import Narrator, NarratorContext, OptionDraft, fill_short_answers
from reroll.params import Params, default_params
from reroll.sim import RISK_STATS, Forecast
from reroll.storage import RepoCorrupt, RepoNotFound, load_repo, save_repo


class ObservatoryError(Exception):
    """A user-facing error with an HTTP-style status code."""

    def __init__(self, status: int, detail: str, **extra: object) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra  # structured details for the UI, e.g. which options need a type


OPTION_RUNS = 120


class Pending(BaseModel):
    """Today's proposed decision, kept until it is committed so GET and POST see the same options."""

    decision: str
    options: list[Option]
    context: NarratorContext
    custom: bool = False
    guessed: list[str] = Field(default_factory=list)  # ids of options whose action type was guessed


class CommitRequest(BaseModel):
    option: str


class WhatifRequest(BaseModel):
    commit: str
    option: str


class CheckoutRequest(BaseModel):
    branch: str


class OptionIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    action: str | None = None  # None = let the narrator guess


class DecisionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=140)
    options: list[OptionIn] = Field(min_length=ops.MIN_OPTIONS, max_length=ops.MAX_OPTIONS)


def _forecast_json(f: Forecast) -> dict:
    return {
        "risk": f.risk,
        "danger_prob": f.danger_prob,
        "days": f.days,
        "runs": f.runs,
        "bands": {s: [vars(b) for b in f.bands[s]] for s in STAT_NAMES},
        "paths": f.paths,
    }


def _fork_day(repo: Repo, name: str) -> int | None:
    """Day a branch forked at (0 = the very beginning); None for main."""
    if name == "main":
        return None
    at = repo.branches[name].created_from
    return repo.get_commit(at).day if at else 0


class Observatory:
    def __init__(self, path: Path, params: Params | None = None, narrator: Narrator | None = None) -> None:
        self.path = path
        self.params = params or default_params()
        if narrator is None:
            from reroll.claude_narrator import make_narrator  # not needed (or available) in the browser

            narrator = make_narrator()
        self.narrator = narrator
        self.lock = threading.Lock()
        self.pending: dict[tuple[str, str | None], Pending] = {}

    # ------------------------------------------------------------ helpers

    def load(self) -> Repo:
        try:
            return load_repo(self.path)
        except RepoNotFound:
            raise ObservatoryError(404, t("err.not_found", "en", path=self.path))
        except RepoCorrupt as e:
            raise ObservatoryError(500, t("err.corrupt", "en", path=e.path, detail=e.detail))

    def fail(self, repo: Repo, e: ops.OpError) -> ObservatoryError:
        return ObservatoryError(400, t(e.key, repo.meta.lang, **e.kwargs))

    def pending_for(self, repo: Repo) -> Pending:
        key = self.head_key(repo)
        if key not in self.pending:
            ctx = ops.narrator_context(repo, self.params)
            proposal = self.narrator.propose(ctx)
            options = ops.build_options(proposal.options, self.params, ops.rng_for(repo, proposal.decision))
            self.pending[key] = Pending(decision=proposal.decision, options=options, context=ctx)
        return self.pending[key]

    def head_key(self, repo: Repo) -> tuple[str, str | None]:
        h = ops.head(repo)
        return (repo.current_branch, h.id if h else None)

    def narrate(self, ctx: NarratorContext, c: Commit) -> str | None:
        c.narration = self.narrator.narrate(ctx, c)
        return getattr(self.narrator, "last_fallback_reason", None)

    # ------------------------------------------------------------ the page's whole world, as JSON

    def snapshot(self, repo: Repo, notice: str | None = None) -> dict:
        p = self.params
        h = ops.head(repo)
        path = list(reversed(ops.history(repo)))
        on_path = {c.id for c in path}

        def commit_json(c: Commit) -> dict:
            start = ops.start_of_day_state(repo, c, p)
            return {
                "id": c.id,
                "day": c.day,
                "decision": c.decision,
                "chosen": c.chosen,
                "options": [
                    {
                        "id": o.id,
                        "label": o.label,
                        "action": o.action,
                        "effects": o.effects,
                        "state_if": rules.apply_effects(start, o.effects, repo.state_schema).model_dump(),
                    }
                    for o in c.options
                ],
                "state": c.state_after.model_dump(),
                "carryover": c.carryover,
                "risk": c.risk,
                "narration": c.narration,
            }

        others = []
        for name, b in repo.branches.items():
            if name == repo.current_branch or not b.head:
                continue
            bpath = list(reversed(ops.history(repo.model_copy(update={"current_branch": name}))))
            split = next((i for i, c in enumerate(bpath) if c.id not in on_path), None)
            if split is None:
                continue
            anchor = (
                {"day": 0, "state": repo.initial_state.model_dump()}
                if split == 0
                else {"day": bpath[split - 1].day, "state": bpath[split - 1].state_after.model_dump()}
            )
            points = [anchor] + [{"day": c.day, "state": c.state_after.model_dump()} for c in bpath[split:]]
            others.append({"name": name, "points": points})

        pend = self.pending_for(repo)
        day = ops.next_day(repo)
        return {
            "lang": repo.meta.lang,
            "narrator": type(self.narrator).__name__,
            "notice": notice,
            "branch": repo.current_branch,
            "branches": [
                {
                    "name": name,
                    "current": name == repo.current_branch,
                    "head_day": repo.get_commit(b.head).day if b.head else 0,
                    "from_day": _fork_day(repo, name),
                }
                for name, b in repo.branches.items()
            ],
            "initial": repo.initial_state.model_dump(),
            "state": ops.current_state(repo).model_dump(),
            "today": h.day if h else 0,
            "tags": [tag.model_dump() for tag in ops.active_tags(repo, day)],
            "path": [commit_json(c) for c in path],
            "others": others,
            # effects of today's options are deliberately left out: they are revealed on collapse
            "decision": {
                "day": day,
                "question": pend.decision,
                "custom": pend.custom,
                "options": [
                    {
                        "id": o.id,
                        "label": o.label,
                        "action": o.action,
                        "hint": p.describe(o.action, repo.meta.lang),
                        "guessed": o.id in pend.guessed,
                    }
                    for o in pend.options
                ],
            },
            "actions": pend.context.actions,
            "forecast": _forecast_json(ops.forecast(repo, p, keep_paths=True)),
            "option_forecasts": {
                o.id: _forecast_json(ops.forecast(repo, p, runs=OPTION_RUNS, first_action=o.action, keep_paths=True))
                for o in pend.options
            },
            "bounds": {s: [b.min, b.max] for s, b in repo.state_schema.items()},
            "danger_below": p.simulation.danger_below,
            "risk_stats": list(RISK_STATS),
        }

    # ------------------------------------------------------------ actions

    def state(self) -> dict:
        with self.lock:
            return self.snapshot(self.load())

    def commit(self, option: str) -> dict:
        with self.lock:
            repo = self.load()
            pend = self.pending_for(repo)
            if option not in {o.id for o in pend.options}:
                ids = ", ".join(o.id for o in pend.options)
                raise ObservatoryError(400, t("commit.bad_choice", repo.meta.lang, choice=option, ids=ids))
            self.pending.pop(self.head_key(repo), None)
            c = ops.commit(repo, pend.decision, pend.options, option, self.params)
            reason = self.narrate(pend.context, c)
            save_repo(repo, self.path)
            return self.snapshot(repo, notice=reason and t("narrator.fallback", repo.meta.lang, reason=reason))

    def whatif(self, commit: str, option: str) -> dict:
        with self.lock:
            repo = self.load()
            try:
                target = ops.resolve_commit(repo, commit)
                ops.whatif_option(target, option)
                ops.fork_before(repo, target)
            except ops.OpError as e:
                raise self.fail(repo, e)
            ctx = ops.narrator_context(repo, self.params)
            c = ops.commit(repo, target.decision, target.options, option, self.params)
            reason = self.narrate(ctx, c)
            save_repo(repo, self.path)
            return self.snapshot(repo, notice=reason and t("narrator.fallback", repo.meta.lang, reason=reason))

    def set_decision(self, req: DecisionRequest) -> dict:
        """Replace today's proposed decision with the player's own question and options."""
        with self.lock:
            repo = self.load()
            lang, actions = repo.meta.lang, self.params.actions
            types = ", ".join(actions)
            for o in req.options:
                if o.action is not None and not self.params.is_action(o.action):
                    raise ObservatoryError(400, t("custom.bad_type", lang, action=o.action, types=types))
            ctx = ops.narrator_context(repo, self.params)
            missing = [i for i, o in enumerate(req.options) if o.action is None]
            guesses = dict(zip(missing, self.narrator.classify(ctx, req.question, [req.options[i].label for i in missing])))
            known = [o.action or guesses.get(i) for i, o in enumerate(req.options)]
            known = fill_short_answers([o.label for o in req.options], known, actions)
            guesses.update({i: a for i, a in enumerate(known) if i in missing and a})
            unknown = [o.label for i, o in enumerate(req.options) if not known[i]]
            if unknown:
                raise ObservatoryError(400, t("custom.unknown", lang, label=unknown[0], types=types), unknown=unknown)
            drafts = [
                OptionDraft(label=o.label.strip(), action=o.action or guesses[i]) for i, o in enumerate(req.options)
            ]
            try:
                options = ops.custom_options(repo, self.params, req.question, drafts)
            except ops.OpError as e:
                raise self.fail(repo, e)
            self.pending[self.head_key(repo)] = Pending(
                decision=req.question.strip(), options=options, context=ctx, custom=True,
                guessed=[options[i].id for i in missing],
            )
            return self.snapshot(repo)

    def reset_decision(self) -> dict:
        with self.lock:
            repo = self.load()
            self.pending.pop(self.head_key(repo), None)
            return self.snapshot(repo)

    def checkout(self, branch: str) -> dict:
        with self.lock:
            repo = self.load()
            try:
                ops.checkout(repo, branch)
            except ops.OpError as e:
                raise self.fail(repo, e)
            save_repo(repo, self.path)
            return self.snapshot(repo)


    # ------------------------------------------------------------ one entry point for every transport

    def dispatch(self, method: str, route: str, payload: dict | None = None) -> dict:
        """Run an API route. Used by the browser build, where there is no HTTP server."""
        try:
            if (method, route) == ("GET", "/api/state"):
                return self.state()
            if (method, route) == ("POST", "/api/commit"):
                return self.commit(CommitRequest.model_validate(payload).option)
            if (method, route) == ("POST", "/api/whatif"):
                req = WhatifRequest.model_validate(payload)
                return self.whatif(req.commit, req.option)
            if (method, route) == ("POST", "/api/decision"):
                return self.set_decision(DecisionRequest.model_validate(payload))
            if (method, route) == ("POST", "/api/decision/reset"):
                return self.reset_decision()
            if (method, route) == ("POST", "/api/checkout"):
                return self.checkout(CheckoutRequest.model_validate(payload).branch)
        except ValidationError as e:
            raise ObservatoryError(422, str(e.errors()[0]["msg"])) from e
        raise ObservatoryError(404, f"no route {method} {route}")
