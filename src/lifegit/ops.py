"""Repository operations behind init / commit / log etc. No I/O here."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date

from lifegit import rules
from lifegit.i18n import DEFAULT_LANG, Lang
from lifegit.models import Commit, Meta, Option, Repo, State, Tag
from lifegit.narrator import NarratorContext, OptionDraft
from lifegit.params import Params


def new_repo(name: str, params: Params, today: date, lang: Lang = DEFAULT_LANG) -> Repo:
    return Repo(
        meta=Meta(name=name, created_at=today, lang=lang),
        state_schema=params.stats,
        initial_state=params.initial_state,
    )


def head(repo: Repo) -> Commit | None:
    head_id = repo.branches[repo.current_branch].head
    return repo.get_commit(head_id) if head_id else None


def current_state(repo: Repo) -> State:
    h = head(repo)
    return h.state_after if h else repo.initial_state


def next_day(repo: Repo) -> int:
    h = head(repo)
    return h.day + 1 if h else 1


def active_tags(repo: Repo, day: int) -> list[Tag]:
    h = head(repo)
    return rules.expire_tags(h.tags_active, day) if h else []


def history(repo: Repo, limit: int | None = None) -> list[Commit]:
    """Walk back from HEAD along parents, newest first."""
    out: list[Commit] = []
    c = head(repo)
    while c is not None and (limit is None or len(out) < limit):
        out.append(c)
        c = repo.get_commit(c.parent) if c.parent else None
    return out


def narrator_context(repo: Repo, params: Params, recent: int = 5) -> NarratorContext:
    day = next_day(repo)
    lang = repo.meta.lang
    return NarratorContext(
        lang=lang,
        day=day,
        state=current_state(repo),
        tags=active_tags(repo, day),
        recent=[
            f"Day {c.day}: {c.decision} → {c.chosen_option.label}"
            for c in reversed(history(repo, recent))
        ],
        actions={name: a.description.get(lang) for name, a in params.actions.items()},
    )


def rng_for(repo: Repo, decision: str) -> random.Random:
    """RNG determined by (HEAD, day, decision): the same inputs roll the same numbers."""
    h = head(repo)
    key = f"{h.id if h else 'root'}|{next_day(repo)}|{decision}"
    return random.Random(hashlib.sha256(key.encode()).hexdigest())


def build_options(drafts: list[OptionDraft], params: Params, rng: random.Random) -> list[Option]:
    """Turn the narrator's drafts into options with numbers. Numbers come only from the action table."""
    options = []
    for i, d in enumerate(drafts):
        if d.action not in params.actions:
            raise ValueError(f"unknown action {d.action!r}")
        effects = rules.clamp_effects(rules.roll_effects(params.actions[d.action], rng), params.stats)
        options.append(Option(id=chr(ord("a") + i), label=d.label, action=d.action, effects=effects))
    return options


def _commit_id(repo: Repo, payload: dict) -> str:
    existing = {c.id for c in repo.commits}
    salt = 0
    while True:
        raw = json.dumps({**payload, "salt": salt}, sort_keys=True, ensure_ascii=False)
        cid = hashlib.sha1(raw.encode()).hexdigest()[:7]
        if cid not in existing:
            return cid
        salt += 1


def commit(repo: Repo, decision: str, options: list[Option], chosen: str, params: Params) -> Commit:
    """Apply the chosen option, record a new commit and advance the current branch. Mutates repo."""
    option = next((o for o in options if o.id == chosen), None)
    if option is None:
        raise ValueError(f"chosen {chosen!r} not in options")

    h = head(repo)
    day = next_day(repo)
    state_after = rules.apply_effects(current_state(repo), option.effects, repo.state_schema)
    tags = rules.update_tags(h.tags_active if h else [], params.actions[option.action], day)

    payload = {
        "parent": h.id if h else None,
        "branch": repo.current_branch,
        "day": day,
        "decision": decision,
        "options": [o.model_dump() for o in options],
        "chosen": chosen,
    }
    c = Commit(
        id=_commit_id(repo, payload),
        parent=h.id if h else None,
        branch=repo.current_branch,
        day=day,
        decision=decision,
        options=options,
        chosen=chosen,
        state_after=state_after,
        tags_active=tags,
        risk=rules.assess_risk(state_after),
    )
    repo.commits.append(c)
    repo.branches[repo.current_branch].head = c.id
    return c
