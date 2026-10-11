"""Local web server for the Observatory UI (`life serve`).

life.json stays the single source of truth: every request reads it and every change writes it,
so the CLI and the browser always agree. The browser never sees the effects of today's options
before you choose; they are revealed only after the commit ("collapse").
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reroll import ops, rules
from reroll.claude_narrator import make_narrator
from reroll.i18n import t
from reroll.models import STAT_NAMES, Commit, Option, Repo
from reroll.narrator import Narrator, NarratorContext, OptionDraft
from reroll.params import Params, default_params
from reroll.sim import RISK_STATS, Forecast
from reroll.storage import RepoCorrupt, RepoNotFound, load_repo, save_repo

WEB_DIR = Path(__file__).with_name("web")
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
        self.narrator = narrator or make_narrator()
        self.lock = threading.Lock()
        self.pending: dict[tuple[str, str | None], Pending] = {}

    # ------------------------------------------------------------ helpers

    def load(self) -> Repo:
        try:
            return load_repo(self.path)
        except RepoNotFound:
            raise HTTPException(404, t("err.not_found", "en", path=self.path))
        except RepoCorrupt as e:
            raise HTTPException(500, t("err.corrupt", "en", path=e.path, detail=e.detail))

    def fail(self, repo: Repo, e: ops.OpError) -> HTTPException:
        return HTTPException(400, t(e.key, repo.meta.lang, **e.kwargs))

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
                        "hint": pend.context.actions[o.action],
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

    def commit(self, option: str) -> dict:
        with self.lock:
            repo = self.load()
            pend = self.pending_for(repo)
            if option not in {o.id for o in pend.options}:
                ids = ", ".join(o.id for o in pend.options)
                raise HTTPException(400, t("commit.bad_choice", repo.meta.lang, choice=option, ids=ids))
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
                if o.action is not None and o.action not in actions:
                    raise HTTPException(400, t("custom.bad_type", lang, action=o.action, types=types))
            ctx = ops.narrator_context(repo, self.params)
            missing = [i for i, o in enumerate(req.options) if o.action is None]
            guesses = dict(zip(missing, self.narrator.classify(ctx, req.question, [req.options[i].label for i in missing])))
            drafts = []
            for i, o in enumerate(req.options):
                action = o.action or guesses.get(i)
                if action is None:
                    raise HTTPException(400, t("custom.unknown", lang, label=o.label, types=types))
                drafts.append(OptionDraft(label=o.label.strip(), action=action))
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


def create_app(path: Path, params: Params | None = None, narrator: Narrator | None = None) -> FastAPI:
    obs = Observatory(path, params, narrator)
    app = FastAPI(title="Reroll Observatory", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.get("/api/state")
    def state() -> dict:
        with obs.lock:
            return obs.snapshot(obs.load())

    @app.post("/api/commit")
    def commit(req: CommitRequest) -> dict:
        return obs.commit(req.option)

    @app.post("/api/whatif")
    def whatif(req: WhatifRequest) -> dict:
        return obs.whatif(req.commit, req.option)

    @app.post("/api/decision")
    def decision(req: DecisionRequest) -> dict:
        return obs.set_decision(req)

    @app.post("/api/decision/reset")
    def reset_decision() -> dict:
        return obs.reset_decision()

    @app.post("/api/checkout")
    def checkout(req: CheckoutRequest) -> dict:
        return obs.checkout(req.branch)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
