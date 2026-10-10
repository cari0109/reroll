"""Command-line entry point. Only handles I/O; logic lives in ops / rules / narrator."""

from __future__ import annotations

import os
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from reroll import graph, ops
from reroll.i18n import DEFAULT_LANG, LANGS, Lang, t
from reroll.models import STAT_NAMES, Commit, Repo, State, Tag
from reroll.claude_narrator import make_narrator
from reroll.narrator import Narrator, format_effects
from reroll.params import default_params
from reroll.storage import DEFAULT_FILE, RepoCorrupt, RepoNotFound, load_repo, save_repo

app = typer.Typer(help="Reroll: git log --graph, but for your life. For entertainment only.", no_args_is_help=True)
console = Console()

RISK_STYLE = {"low": "green", "medium": "yellow", "high": "bold red"}
LANE_COLORS = ["yellow", "magenta", "cyan", "green", "blue", "red"]

LangOption = Enum("LangOption", {lang: lang for lang in LANGS}, type=str)


def _fallback_lang() -> Lang:
    """Language for messages printed before a repo is loaded."""
    env = os.environ.get("LIFE_LANG")
    return env if env in LANGS else DEFAULT_LANG  # type: ignore[return-value]


def _fail(message: str, lang: Lang) -> typer.Exit:
    console.print(f"[red]{t('error', lang)}[/] {message}")
    return typer.Exit(1)


def _op_fail(e: ops.OpError, lang: Lang) -> typer.Exit:
    kwargs = {k: escape(v) if isinstance(v, str) else v for k, v in e.kwargs.items()}
    return _fail(t(e.key, lang, **kwargs), lang)


@app.callback()
def main(
    ctx: typer.Context,
    file: Path = typer.Option(Path(DEFAULT_FILE), "--file", "-f", envvar="LIFE_FILE", help="Life repository file."),
) -> None:
    ctx.obj = file


def _load(ctx: typer.Context) -> Repo:
    lang = _fallback_lang()
    try:
        return load_repo(ctx.obj)
    except RepoNotFound as e:
        raise _fail(t("err.not_found", lang, path=escape(str(e.path))), lang)
    except RepoCorrupt as e:
        raise _fail(t("err.corrupt", lang, path=escape(str(e.path)), detail=escape(e.detail)), lang)


# ---------------------------------------------------------------- rendering


def _bar_style(value: int) -> str:
    if value < 20:
        return "red"
    if value < 35:
        return "yellow"
    return "green"


def _state_table(state: State, lang: Lang, before: State | None = None) -> Table:
    table = Table.grid(padding=(0, 2))
    for stat in STAT_NAMES:
        v = getattr(state, stat)
        filled = round(v / 5)
        bar = Text("█" * filled, style=_bar_style(v)) + Text("░" * (20 - filled), style="dim")
        row = [Text(t(f"stat.{stat}", lang), style="bold"), bar, Text(f"{v:>3}")]
        if before is not None:
            d = v - getattr(before, stat)
            row.append(Text(f"{d:+d}" if d else "", style="green" if d > 0 else "red"))
        table.add_row(*row)
    return table


def _tags_text(tags: list[Tag], lang: Lang) -> str:
    if not tags:
        return f"[dim]{t('tags.none', lang)}[/]"
    return "  ".join(
        f"[magenta]{tag.name}[/]"
        + (f" ×{tag.count}" if tag.count > 1 else "")
        + f" [dim]({t('tags.until', lang, day=tag.expires_day)})[/]"
        for tag in tags
    )


def _gutter(markup: str) -> None:
    """Print text after the left graph line; wrapped lines keep the line so the graph never breaks."""
    prefix = Text("│   ", style="yellow")
    lines = Text.from_markup(markup).wrap(console, max(20, console.width - len(prefix))) or [Text()]
    for line in lines:
        console.print(prefix + line)


def _labels(repo: Repo, commit_id: str, refs: dict[str, list[str]]) -> str:
    """git-style ref decoration, e.g. ` (HEAD -> what-if, main)`."""
    names = refs.get(commit_id)
    if not names:
        return ""
    parts = [
        f"[bold cyan]HEAD -> {escape(n)}[/]" if n == repo.current_branch else f"[bold green]{escape(n)}[/]" for n in names
    ]
    return " (" + ", ".join(parts) + ")"


def _describe_commit(repo: Repo, commit_id: str | None, lang: Lang) -> str:
    if commit_id is None:
        return t("branch.root", lang)
    c = repo.get_commit(commit_id)
    return f"[yellow]{c.id}[/] (Day {c.day} · {escape(c.decision)})"


def _color_prefix(prefix: str) -> Text:
    """Color each graph lane consistently; lane i lives at character column 2*i."""
    text = Text()
    for i, ch in enumerate(prefix):
        style = "bold" if ch == "*" else LANE_COLORS[(i // 2) % len(LANE_COLORS)]
        text.append(ch, style=style)
    return text


def _render_commit(c: Commit, labels: str, lang: Lang) -> None:
    console.print(
        f"[yellow]*[/] [yellow]{c.id}[/]{labels} [bold]Day {c.day}[/]  {escape(c.decision)}  "
        f"[{RISK_STYLE[c.risk]}]\\[{c.risk}][/]"
    )
    for o in c.options:
        effects = format_effects(o.effects, lang)
        if o.id == c.chosen:
            _gutter(f"[green]●[/] {escape(o.label)}  [dim]{effects}[/]")
        else:
            _gutter(f"[dim]○ {escape(o.label)}  {effects}  ({t('log.ghost', lang)})[/]")
    if c.narration:
        _gutter(f"[italic]🎙  {escape(c.narration)}[/]")
    _gutter("")


# ---------------------------------------------------------------- commands


@app.command()
def init(
    ctx: typer.Context,
    name: str = typer.Option("my-life", help="Repository name."),
    lang: LangOption = typer.Option(DEFAULT_LANG, "--lang", "-l", help="Language for prompts and narration."),
) -> None:
    """Create a new life repository."""
    path: Path = ctx.obj
    code: Lang = lang.value
    if path.exists():
        raise _fail(t("init.exists", code, path=escape(str(path))), code)
    save_repo(ops.new_repo(name, default_params(), date.today(), code), path)
    console.print(t("init.done", code, path=escape(str(path))))
    console.print(f"[dim]{t('disclaimer', code)}[/]")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show the current branch, stats, and active tags."""
    repo = _load(ctx)
    lang = repo.meta.lang
    day = ops.next_day(repo)
    console.print(t("status.header", lang, branch=repo.current_branch, day=day) + "\n")
    console.print(_state_table(ops.current_state(repo), lang))
    console.print("\n" + t("status.tags", lang, tags=_tags_text(ops.active_tags(repo, day), lang)))


@app.command()
def commit(
    ctx: typer.Context,
    decision: Optional[str] = typer.Argument(None, help="Today's decision; omit to get one from the narrator."),
    choose: Optional[str] = typer.Option(None, "--choose", "-c", help="Pick an option id directly (non-interactive)."),
) -> None:
    """Face a decision, make a choice, and record it as a commit."""
    repo = _load(ctx)
    lang = repo.meta.lang
    params = default_params()
    narrator = make_narrator()

    ctx_before = ops.narrator_context(repo, params)
    with console.status("…"):
        proposal = narrator.propose(ctx_before, decision)
    _note_fallback(narrator, lang)
    options = ops.build_options(proposal.options, params, ops.rng_for(repo, proposal.decision))

    console.print(f"[bold]Day {ctx_before.day}[/] · {escape(proposal.decision)}\n")
    for o in options:
        console.print(f"  [cyan]{o.id}[/]) {escape(o.label)}  [dim]{ctx_before.actions[o.action]}[/]")
    ids = [o.id for o in options]
    if choose is None:
        choose = Prompt.ask("\n" + t("commit.prompt", lang), choices=ids, console=console)
    elif choose not in ids:
        raise _fail(t("commit.bad_choice", lang, choice=choose, ids=", ".join(ids)), lang)

    before = ops.current_state(repo)
    c = ops.commit(repo, proposal.decision, options, choose, params)
    with console.status("…"):
        c.narration = narrator.narrate(ctx_before, c)
    save_repo(repo, ctx.obj)
    _print_result(repo, c, before, lang)
    _note_fallback(narrator, lang)


def _note_fallback(narrator: Narrator, lang: Lang) -> None:
    reason = getattr(narrator, "last_fallback_reason", None)
    if reason:
        console.print(f"[dim]{escape(t('narrator.fallback', lang, reason=reason))}[/]")


def _print_result(repo: Repo, c: Commit, before: State, lang: Lang) -> None:
    console.print(
        f"\n[yellow]\\[{escape(repo.current_branch)} {c.id}][/] {escape(c.chosen_option.label)}  "
        f"{t('commit.risk', lang)}: [{RISK_STYLE[c.risk]}]{c.risk}[/]\n"
    )
    console.print(_state_table(c.state_after, lang, before))
    console.print(Text("\n🎙  " + c.narration))


@app.command()
def whatif(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="The commit (id prefix or branch) whose decision you want to redo."),
    choose: Optional[str] = typer.Option(None, "--choose", "-c", help="Which ghost option to take."),
    name: Optional[str] = typer.Option(None, "--name", help="Branch name (default: whatif/<commit>)."),
) -> None:
    """Go back to a past decision and take the option you didn't. Opens a new branch."""
    repo = _load(ctx)
    lang = repo.meta.lang
    params = default_params()
    try:
        target = ops.resolve_commit(repo, ref)
        ghosts = [o for o in target.options if o.id != target.chosen]
        if choose is None:
            if len(ghosts) == 1:
                choose = ghosts[0].id
            else:
                console.print(f"[bold]Day {target.day}[/] · {escape(target.decision)}\n")
                for o in target.options:
                    label = escape(o.label)
                    if o.id == target.chosen:
                        label = f"[dim strike]{label}[/]"
                    console.print(f"  [cyan]{o.id}[/]) {label}")
                choose = Prompt.ask("\n" + t("whatif.prompt", lang), choices=[o.id for o in ghosts], console=console)
        ops.whatif_option(target, choose)

        ghost = next(o for o in target.options if o.id == choose)
        console.print(
            t("whatif.header", lang, day=target.day, label=escape(ghost.label), orig=escape(target.chosen_option.label))
        )
        ops.fork_before(repo, target, name)
    except ops.OpError as e:
        raise _op_fail(e, lang)

    ctx_before = ops.narrator_context(repo, params)
    before = ops.current_state(repo)
    c = ops.commit(repo, target.decision, target.options, choose, params)
    narrator = make_narrator()
    with console.status("…"):
        c.narration = narrator.narrate(ctx_before, c)
    save_repo(repo, ctx.obj)
    console.print(t("checkout.done", lang, name=escape(repo.current_branch)))
    _print_result(repo, c, before, lang)
    _note_fallback(narrator, lang)


@app.command()
def log(
    ctx: typer.Context,
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max commits to show."),
    show_graph: bool = typer.Option(False, "--graph", "-g", help="One line per commit, all branches, as a graph."),
) -> None:
    """Show history. Default: the current branch in detail, including ghost options you didn't take."""
    repo = _load(ctx)
    lang = repo.meta.lang
    refs = ops.branch_labels(repo)

    if show_graph:
        rows = graph.layout(ops.commits_newest_first(repo))
        if not rows:
            console.print(f"[dim]{t('log.empty', lang, branch=repo.current_branch)}[/]")
            return
        shown = 0
        for row in rows:
            if row.commit is None:
                console.print(_color_prefix(row.prefix))
                continue
            if limit is not None and shown >= limit:
                break
            c = row.commit
            line = _color_prefix(row.prefix) + Text.from_markup(
                f" [yellow]{c.id}[/]{_labels(repo, c.id, refs)} Day {c.day} "
                f"[{RISK_STYLE[c.risk]}]\\[{c.risk}][/] [bold]{escape(c.chosen_option.label)}[/]"
                f"  [dim]{escape(c.decision)}[/]"
            )
            console.print(line, no_wrap=True, overflow="ellipsis")  # wrapping would break the graph
            shown += 1
        else:
            console.print(f"[yellow]○[/] [dim]{t('log.root', lang)}[/]")
        return

    commits = ops.history(repo, limit)
    if not commits:
        console.print(f"[dim]{t('log.empty', lang, branch=repo.current_branch)}[/]")
        return
    for c in commits:
        _render_commit(c, _labels(repo, c.id, refs), lang)
    if commits[-1].parent is None:
        console.print(f"[yellow]○[/] [dim]{t('log.root', lang)}[/]")


@app.command()
def branch(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Name of the new branch; omit to list branches."),
    start: Optional[str] = typer.Argument(None, help="Branch or commit id to fork from (default: HEAD)."),
) -> None:
    """List branches, or create one at any point in your history."""
    repo = _load(ctx)
    lang = repo.meta.lang

    if name is None:
        table = Table.grid(padding=(0, 2))
        for n, b in repo.branches.items():
            mark = "[bold cyan]*[/]" if n == repo.current_branch else " "
            style = "bold cyan" if n == repo.current_branch else ""
            tip = repo.get_commit(b.head) if b.head else None
            fork = (
                f"[dim]{t('branch.from', lang, at=b.created_from or t('branch.root', lang))}[/]"
                if n != "main"
                else ""
            )
            table.add_row(
                mark,
                Text(n, style=style),
                f"[yellow]{tip.id}[/]  Day {tip.day}" if tip else "[dim]-[/]",
                fork,
            )
        console.print(table)
        return

    try:
        b = ops.create_branch(repo, name, start)
    except ops.OpError as e:
        raise _op_fail(e, lang)
    save_repo(repo, ctx.obj)
    console.print(t("branch.created", lang, name=escape(name), at=_describe_commit(repo, b.head, lang)))


@app.command()
def checkout(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Branch to switch to."),
    start: Optional[str] = typer.Argument(None, help="With -b: branch or commit id to fork from (default: HEAD)."),
    new: bool = typer.Option(False, "-b", help="Create the branch first, then switch to it."),
) -> None:
    """Switch branches. `life checkout -b what-if <commit>` rewinds time to that commit."""
    repo = _load(ctx)
    lang = repo.meta.lang
    if start is not None and not new:
        raise typer.BadParameter("START is only allowed together with -b")
    if not new and name == repo.current_branch:
        console.print(t("checkout.already", lang, name=escape(name)))
        return

    old_head = repo.branches[repo.current_branch].head
    try:
        if new:
            ops.create_branch(repo, name, start)
        ops.checkout(repo, name)
    except ops.OpError as e:
        raise _op_fail(e, lang)
    save_repo(repo, ctx.obj)

    console.print(t("checkout.done", lang, name=escape(name)))
    h = ops.head(repo)
    if new and (h.id if h else None) != old_head:
        day = h.day if h else 0
        console.print(t("checkout.rewind", lang, day=day, next=day + 1))


if __name__ == "__main__":
    app()
