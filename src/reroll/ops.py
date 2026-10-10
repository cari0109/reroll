"""Repository operations behind init / commit / log etc. No I/O here."""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date

from reroll import rules
from reroll.i18n import DEFAULT_LANG, Lang
from reroll.models import Branch, Commit, Meta, Option, Repo, State, Tag
from reroll.narrator import NarratorContext, OptionDraft
from reroll.params import Params

# Unicode word chars are allowed so branch names like "如果当初" work.
BRANCH_NAME_RE = re.compile(r"^(?!-)[\w./-]{1,40}$")
MIN_PREFIX = 4


class OpError(Exception):
    """A user-facing error. `key` is an i18n message key, `kwargs` its arguments."""

    def __init__(self, key: str, **kwargs: object) -> None:
        super().__init__(key, kwargs)
        self.key = key
        self.kwargs = kwargs


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


def commits_newest_first(repo: Repo) -> list[Commit]:
    """All commits in a valid topological order: a parent's day is always smaller
    than its child's, so sorting by day works; ties go to the later-created commit."""
    order = {c.id: i for i, c in enumerate(repo.commits)}
    return sorted(repo.commits, key=lambda c: (c.day, order[c.id]), reverse=True)


def branch_labels(repo: Repo) -> dict[str, list[str]]:
    """commit id -> names of branches whose head is that commit (current branch first)."""
    labels: dict[str, list[str]] = {}
    for name in sorted(repo.branches, key=lambda n: n != repo.current_branch):
        head_id = repo.branches[name].head
        if head_id:
            labels.setdefault(head_id, []).append(name)
    return labels


def resolve_ref(repo: Repo, ref: str) -> str | None:
    """Resolve a branch name or a (prefix of a) commit id to a commit id.
    Returns None for a branch with no commits yet."""
    if ref in repo.branches:
        return repo.branches[ref].head
    if len(ref) >= MIN_PREFIX:
        matches = [c.id for c in repo.commits if c.id.startswith(ref.lower())]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise OpError("err.ref_ambiguous", ref=ref, matches=", ".join(matches))
    raise OpError("err.ref_unknown", ref=ref)


def create_branch(repo: Repo, name: str, ref: str | None = None) -> Branch:
    """Create a branch at `ref` (default: current HEAD). Does not switch to it."""
    _check_new_branch_name(repo, name)
    at = resolve_ref(repo, ref) if ref is not None else repo.branches[repo.current_branch].head
    return _add_branch(repo, name, at)


def _check_new_branch_name(repo: Repo, name: str) -> None:
    if not BRANCH_NAME_RE.match(name):
        raise OpError("err.branch_name", name=name)
    if name in repo.branches:
        raise OpError("err.branch_exists", name=name)


def _add_branch(repo: Repo, name: str, at: str | None) -> Branch:
    branch = Branch(head=at, created_from=at)
    repo.branches[name] = branch
    return branch


def checkout(repo: Repo, name: str) -> None:
    if name not in repo.branches:
        raise OpError("err.branch_unknown", name=name)
    repo.current_branch = name


def resolve_commit(repo: Repo, ref: str) -> Commit:
    commit_id = resolve_ref(repo, ref)
    if commit_id is None:  # a branch with no commits yet
        raise OpError("err.ref_unknown", ref=ref)
    return repo.get_commit(commit_id)


def whatif_option(target: Commit, choice: str) -> str:
    """Validate an alternative option for replaying `target`."""
    if choice == target.chosen:
        raise OpError("err.whatif_same", day=target.day)
    ids = [o.id for o in target.options]
    if choice not in ids:
        raise OpError("commit.bad_choice", choice=choice, ids=", ".join(ids))
    return choice


def fork_before(repo: Repo, target: Commit, name: str | None = None) -> str:
    """Create a branch at `target`'s parent and switch to it. Returns the branch name.

    Follow with `commit(repo, target.decision, target.options, <ghost id>, params)`:
    reusing the stored options means the result is exactly the ghost shown in the log.
    """
    if name is None:
        base = name = f"whatif/{target.id}"
        n = 2
        while name in repo.branches:
            name, n = f"{base}-{n}", n + 1
    else:
        _check_new_branch_name(repo, name)

    _add_branch(repo, name, target.parent)
    checkout(repo, name)
    return name


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
