"""Command-line entry point. Only handles I/O; logic lives in ops / rules / narrator."""

from __future__ import annotations

import os
from datetime import date
from enum import Enum
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from reroll import graph, ops, rules, sim
from reroll.i18n import DEFAULT_LANG, LANGS, Lang, t
from reroll.models import STAT_NAMES, Commit, Option, Repo, State, Tag
from reroll.claude_narrator import make_narrator
from reroll.narrator import Narrator, NarratorContext, OptionDraft, fill_short_answers, format_effects
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


def _state_table(
    state: State, lang: Lang, before: State | None = None, outlook: sim.Forecast | None = None
) -> Table:
    table = Table.grid(padding=(0, 2))
    for stat in STAT_NAMES:
        v = getattr(state, stat)
        filled = round(v / 5)
        bar = Text("█" * filled, style=_bar_style(v)) + Text("░" * (20 - filled), style="dim")
        row = [Text(t(f"stat.{stat}", lang), style="bold"), bar, Text(f"{v:>3}")]
        if before is not None:
            d = v - getattr(before, stat)
            row.append(Text(f"{d:+d}" if d else "", style="green" if d > 0 else "red"))
        if outlook is not None:
            band = outlook.at(stat, outlook.days)
            row.append(Text(f"{t('status.in_days', lang, days=outlook.days)}: {band.p10}–{band.p90}", style="dim"))
        table.add_row(*row)
    return table


def _danger_text(prob: float, days: int, lang: Lang) -> str:
    params = default_params()
    names = "/".join(t(f"stat.{s}", lang) for s in sim.RISK_STATS)
    return t(
        "risk.detail", lang, pct=round(prob * 100), days=days, stats=names, below=params.simulation.danger_below
    )


def _day_start_text(repo: Repo, c: Commit, lang: Lang) -> str | None:
    """Explain the start-of-day change: daily drift plus the aftershock of active tags."""
    if not c.carryover:
        return None
    params = default_params()
    parent_tags = repo.get_commit(c.parent).tags_active if c.parent else []
    causes = [
        tag.name + (f" ×{tag.count}" if tag.count > 1 else "")
        for tag in rules.expire_tags(parent_tags, c.day)
        if params.tags[tag.name].carryover
    ]
    tags = (" (" + ", ".join(causes) + ")" if lang == "en" else "（" + "，".join(causes) + "）") if causes else ""
    return t("day.start", lang, tags=tags, effects=format_effects(c.carryover, lang))


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


def _render_commit(repo: Repo, c: Commit, labels: str, lang: Lang) -> None:
    console.print(
        f"[yellow]*[/] [yellow]{c.id}[/]{labels} [bold]Day {c.day}[/]  {escape(c.decision)}  "
        f"[{RISK_STYLE[c.risk]}]\\[{c.risk}][/]"
    )
    day_start = _day_start_text(repo, c, lang)
    if day_start:
        _gutter(f"[dim]{escape(day_start)}[/]")
    for o in c.options:
        effects = format_effects(o.effects, lang)
        if o.id == c.chosen:
            _gutter(f"[green]●[/] {escape(o.label)}  [dim]{effects}[/]")
        else:
            _gutter(f"[dim]○ {escape(o.label)}  {effects}  ({t('log.ghost', lang)})[/]")
    if c.narration:
        for line in _narration_lines(c.narration, console.width - 4):
            console.print(Text("│   ", style="yellow") + line)
    _gutter("")


def _narration_lines(narration: str, width: int) -> list[Text]:
    """Wrap narration with a hanging indent after the mic icon. Wrapping the text on its
    own matters for CJK: it has no spaces, so rich would otherwise push the whole
    sentence onto the line below the icon."""
    body = Text(narration, style="italic").wrap(console, max(10, width - 4))
    return [Text("🎙  " if i == 0 else "    ") + line for i, line in enumerate(body)]


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
    outlook = ops.forecast(repo, default_params())
    console.print(_state_table(ops.current_state(repo), lang, outlook=outlook))
    console.print("\n" + t("status.tags", lang, tags=_tags_text(ops.active_tags(repo, day), lang)))
    console.print(
        f"{t('commit.risk', lang)}: [{RISK_STYLE[outlook.risk]}]{outlook.risk}[/]  "
        f"[dim]{escape(_danger_text(outlook.danger_prob, outlook.days, lang))}[/]"
    )


@app.command()
def commit(
    ctx: typer.Context,
    decision: Optional[str] = typer.Argument(None, help="Today's decision; omit to get one from the narrator."),
    choose: Optional[str] = typer.Option(None, "--choose", "-c", help="Pick an option id directly (non-interactive)."),
    option: Optional[List[str]] = typer.Option(
        None, "--option", "-o",
        help="Write your own option (2-4 times). Add ':type' to set its action type, e.g. -o 'Go hiking:exercise'.",
    ),
) -> None:
    """Face a decision, make a choice, and record it as a commit."""
    repo = _load(ctx)
    lang = repo.meta.lang
    params = default_params()
    narrator = make_narrator()
    interactive = choose is None

    ctx_before = ops.narrator_context(repo, params)
    guessed: set[str] = set()
    if option:
        try:
            decision, options, guessed = _custom_decision(repo, narrator, ctx_before, decision, option, interactive)
        except ops.OpError as e:
            raise _op_fail(e, lang)
    else:
        with console.status("…"):
            proposal = narrator.propose(ctx_before, decision)
        _note_fallback(narrator, lang)
        decision = proposal.decision
        options = ops.build_options(proposal.options, params, ops.rng_for(repo, decision))

    console.print(f"[bold]Day {ctx_before.day}[/] · {escape(decision)}\n")
    _print_options(options, ctx_before, guessed, lang)
    ids = [o.id for o in options]
    if choose is None:
        choose = Prompt.ask("\n" + t("commit.prompt", lang), choices=ids, console=console)
    elif choose not in ids:
        raise _fail(t("commit.bad_choice", lang, choice=choose, ids=", ".join(ids)), lang)

    before = ops.current_state(repo)
    c = ops.commit(repo, decision, options, choose, params)
    with console.status("…"):
        c.narration = narrator.narrate(ctx_before, c)
    save_repo(repo, ctx.obj)
    _print_result(repo, c, before, lang)
    _note_fallback(narrator, lang)


def _note_fallback(narrator: Narrator, lang: Lang) -> None:
    reason = getattr(narrator, "last_fallback_reason", None)
    if reason:
        console.print(f"[dim]{escape(t('narrator.fallback', lang, reason=reason))}[/]")


def _print_options(options: list[Option], nctx: NarratorContext, guessed: set[str], lang: Lang) -> None:
    for o in options:
        mark = f" [dim italic]({t('custom.guessed', lang)})[/]" if o.id in guessed else ""
        console.print(f"  [cyan]{o.id}[/]) {escape(o.label)}  [dim]{default_params().describe(o.action, lang)}[/]{mark}")


def _custom_decision(
    repo: Repo, narrator: Narrator, nctx: NarratorContext, decision: str | None, specs: list[str], interactive: bool
) -> tuple[str, list[Option], set[str]]:
    """Build today's options from what the player wrote. Missing action types are guessed by the
    narrator; in interactive mode the player confirms or corrects the guesses."""
    params, lang = default_params(), repo.meta.lang
    if not decision or not decision.strip():
        raise ops.OpError("custom.need_question")
    parsed = [ops.parse_option_spec(spec, params.actions) for spec in specs]
    if not ops.MIN_OPTIONS <= len(parsed) <= ops.MAX_OPTIONS:
        raise ops.OpError("custom.count", n=len(parsed))

    missing = [i for i, (_, action) in enumerate(parsed) if action is None]
    guesses: dict[int, str | None] = {}
    if missing:
        with console.status("…"):
            guesses = dict(zip(missing, narrator.classify(nctx, decision, [parsed[i][0] for i in missing])))
        _note_fallback(narrator, lang)

    types = list(params.actions)
    known = fill_short_answers(
        [label for label, _ in parsed], [action or guesses.get(i) for i, (_, action) in enumerate(parsed)], types
    )
    guesses.update({i: a for i, a in enumerate(known) if i in missing and a})
    drafts, guessed = [], set()
    for i, (label, action) in enumerate(parsed):
        if action is None:
            action = guesses.get(i)
            if action is None:
                if not interactive:
                    raise ops.OpError("custom.unknown", label=label, types=", ".join(types))
                action = Prompt.ask(t("custom.pick", lang, label=label), choices=types, console=console)
            else:
                guessed.add(i)
        drafts.append(OptionDraft(label=label, action=action))

    if guessed and interactive:
        preview = ops.custom_options(repo, params, decision, drafts)
        _print_options(preview, nctx, {preview[i].id for i in guessed}, lang)
        if not Confirm.ask(t("custom.confirm", lang), default=True, console=console):
            for i in sorted(guessed):
                drafts[i].action = Prompt.ask(
                    t("custom.pick", lang, label=drafts[i].label), choices=types, default=drafts[i].action, console=console
                )
        guessed = set()  # the player has looked at every type now
        console.print()

    options = ops.custom_options(repo, params, decision, drafts)
    return decision.strip(), options, {options[i].id for i in guessed}


def _print_result(repo: Repo, c: Commit, before: State, lang: Lang) -> None:
    console.print(
        f"\n[yellow]\\[{escape(repo.current_branch)} {c.id}][/] {escape(c.chosen_option.label)}  "
        f"{t('commit.risk', lang)}: [{RISK_STYLE[c.risk]}]{c.risk}[/]"
    )
    if c.danger_prob is not None:
        days = default_params().simulation.horizon
        console.print(f"[dim]{escape(_danger_text(c.danger_prob, days, lang))}[/]")
    day_start = _day_start_text(repo, c, lang)
    if day_start:
        console.print(f"[dim]{escape(day_start)}[/]")
    console.print()
    console.print(_state_table(c.state_after, lang, before))
    console.print()
    for line in _narration_lines(c.narration, console.width):
        console.print(line)


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
        _render_commit(repo, c, _labels(repo, c.id, refs), lang)
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


@app.command()
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", help="Address to bind. Keep the default unless you know you need another."),
    port: int = typer.Option(8000, help="Port to listen on."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the Observatory in your browser."),
) -> None:
    """Open the Observatory web UI for this life repository."""
    import threading
    import webbrowser

    import uvicorn

    from reroll.server import create_app

    repo = _load(ctx)
    url = f"http://{host}:{port}"
    console.print(t("serve.running", repo.meta.lang, url=url))
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(ctx.obj), host=host, port=port, log_level="warning")


BAND_WIDTH = 40
SPARK = "▁▂▃▄▅▆▇█"


def _band_bar(band: sim.Band, now: int, lo: int, hi: int) -> Text:
    """The Schrödinger band: where a stat may be after N days, on a lo..hi axis."""

    def col(v: int) -> int:
        return round((v - lo) / (hi - lo) * (BAND_WIDTH - 1))

    cells = [("·", "dim")] * BAND_WIDTH
    for i in range(col(band.p10), col(band.p90) + 1):
        cells[i] = ("░", "cyan")
    for i in range(col(band.p25), col(band.p75) + 1):
        cells[i] = ("▒", "cyan")
    cells[col(band.p50)] = ("█", "bold cyan")
    cells[col(now)] = ("│", "bold yellow")
    text = Text()
    for ch, style in cells:
        text.append(ch, style=style)
    return text


SPARK_MAX_POINTS = 14


def _sparkline(values: list[int], lo: int, hi: int) -> str:
    if len(values) > SPARK_MAX_POINTS:  # sample evenly, always keeping the last day
        step = (len(values) - 1) / (SPARK_MAX_POINTS - 1)
        values = [values[round(i * step)] for i in range(SPARK_MAX_POINTS)]
    return "".join(SPARK[round((v - lo) / (hi - lo) * (len(SPARK) - 1))] for v in values)


@app.command()
def forecast(
    ctx: typer.Context,
    days: Optional[int] = typer.Option(None, "--days", "-d", min=1, max=90, help="How many days ahead."),
) -> None:
    """Simulate many possible futures from here and show where each stat may land."""
    repo = _load(ctx)
    lang = repo.meta.lang
    params = default_params()
    outlook = ops.forecast(repo, params, days)
    now = ops.current_state(repo)

    console.print(t("forecast.header", lang, runs=outlook.runs, days=outlook.days, day=outlook.start_day + outlook.days - 1))
    console.print(f"[dim]{t('disclaimer', lang)}[/]\n")
    table = Table.grid(padding=(0, 2))
    for stat in STAT_NAMES:
        bounds = repo.state_schema[stat]
        band = outlook.at(stat, outlook.days)
        medians = [b.p50 for b in outlook.bands[stat]]
        table.add_row(
            Text(t(f"stat.{stat}", lang), style="bold"),
            _band_bar(band, getattr(now, stat), bounds.min, bounds.max),
            Text(f"{band.p50:>3}", style="bold cyan"),
            Text(f"{band.p10}–{band.p90}", style="dim"),
            Text(_sparkline(medians, bounds.min, bounds.max), style="cyan"),
        )
    console.print(table)
    console.print(f"\n[dim]{t('forecast.legend', lang)}[/]")
    console.print(
        f"{t('commit.risk', lang)}: [{RISK_STYLE[outlook.risk]}]{outlook.risk}[/]  "
        f"[dim]{escape(_danger_text(outlook.danger_prob, outlook.days, lang))}[/]"
    )


if __name__ == "__main__":
    app()
