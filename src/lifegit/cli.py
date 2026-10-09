"""Command-line entry point. Only handles I/O; logic lives in ops / rules / narrator."""

from __future__ import annotations

import os
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from lifegit import ops
from lifegit.i18n import DEFAULT_LANG, LANGS, Lang, t
from lifegit.models import STAT_NAMES, Commit, Repo, State, Tag
from lifegit.narrator import MockNarrator, format_effects
from lifegit.params import default_params
from lifegit.storage import DEFAULT_FILE, RepoCorrupt, RepoNotFound, load_repo, save_repo

app = typer.Typer(help="LifeGit: git log --graph, but for your life. For entertainment only.", no_args_is_help=True)
console = Console()

RISK_STYLE = {"low": "green", "medium": "yellow", "high": "bold red"}

LangOption = Enum("LangOption", {lang: lang for lang in LANGS}, type=str)


def _fallback_lang() -> Lang:
    """Language for messages printed before a repo is loaded."""
    env = os.environ.get("LIFE_LANG")
    return env if env in LANGS else DEFAULT_LANG  # type: ignore[return-value]


def _fail(message: str, lang: Lang) -> typer.Exit:
    console.print(f"[red]{t('error', lang)}[/] {message}")
    return typer.Exit(1)


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
        raise _fail(t("err.not_found", lang, path=e.path), lang)
    except RepoCorrupt as e:
        raise _fail(t("err.corrupt", lang, path=e.path, detail=e.detail), lang)


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


def _render_commit(c: Commit, labels: str, lang: Lang) -> None:
    console.print(
        f"[yellow]*[/] [yellow]{c.id}[/]{labels} [bold]Day {c.day}[/]  {c.decision}  "
        f"[{RISK_STYLE[c.risk]}]\\[{c.risk}][/]"
    )
    for o in c.options:
        effects = format_effects(o.effects, lang)
        if o.id == c.chosen:
            _gutter(f"[green]●[/] {o.label}  [dim]{effects}[/]")
        else:
            _gutter(f"[dim]○ {o.label}  {effects}  ({t('log.ghost', lang)})[/]")
    if c.narration:
        _gutter(f"[italic]🎙  {c.narration}[/]")
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
        raise _fail(t("init.exists", code, path=path), code)
    save_repo(ops.new_repo(name, default_params(), date.today(), code), path)
    console.print(t("init.done", code, path=path))
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
    narrator = MockNarrator()

    ctx_before = ops.narrator_context(repo, params)
    proposal = narrator.propose(ctx_before, decision)
    options = ops.build_options(proposal.options, params, ops.rng_for(repo, proposal.decision))

    console.print(f"[bold]Day {ctx_before.day}[/] · {proposal.decision}\n")
    for o in options:
        console.print(f"  [cyan]{o.id}[/]) {o.label}  [dim]{ctx_before.actions[o.action]}[/]")
    ids = [o.id for o in options]
    if choose is None:
        choose = Prompt.ask("\n" + t("commit.prompt", lang), choices=ids, console=console)
    elif choose not in ids:
        raise _fail(t("commit.bad_choice", lang, choice=choose, ids=", ".join(ids)), lang)

    before = ops.current_state(repo)
    c = ops.commit(repo, proposal.decision, options, choose, params)
    c.narration = narrator.narrate(ctx_before, c)
    save_repo(repo, ctx.obj)

    console.print(
        f"\n[yellow]\\[{repo.current_branch} {c.id}][/] {c.chosen_option.label}  "
        f"{t('commit.risk', lang)}: [{RISK_STYLE[c.risk]}]{c.risk}[/]\n"
    )
    console.print(_state_table(c.state_after, lang, before))
    console.print(f"\n🎙  {c.narration}")


@app.command()
def log(ctx: typer.Context, limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max commits to show.")) -> None:
    """Show the current branch's history, including ghost options you didn't take."""
    repo = _load(ctx)
    lang = repo.meta.lang
    commits = ops.history(repo, limit)
    if not commits:
        console.print(f"[dim]{t('log.empty', lang, branch=repo.current_branch)}[/]")
        return
    for i, c in enumerate(commits):
        labels = f" ([bold cyan]HEAD -> {repo.current_branch}[/])" if i == 0 else ""
        _render_commit(c, labels, lang)
    if commits[-1].parent is None:
        console.print(f"[yellow]○[/] [dim]{t('log.root', lang)}[/]")


if __name__ == "__main__":
    app()
