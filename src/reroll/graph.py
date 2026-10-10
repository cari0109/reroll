"""Lane layout for `log --graph`, in the style of `git log --graph`.

Life history is a tree (no merges), so each commit has at most one parent.
We walk commits newest-first and keep a list of lanes, each lane holding the
id of the commit it is waiting for. When several lanes wait for the same
parent, the branches fork there and the extra lanes are joined back in.
"""

from __future__ import annotations

from dataclasses import dataclass

from reroll.models import Commit


@dataclass
class GraphRow:
    prefix: str
    commit: Commit | None  # None for connector rows


def layout(commits: list[Commit]) -> list[GraphRow]:
    """`commits` must be newest-first in topological order (children before parents)."""
    lanes: list[str | None] = []
    rows: list[GraphRow] = []

    for c in commits:
        matches = [i for i, lane in enumerate(lanes) if lane == c.id]
        if not matches:  # a branch tip: take a free lane or open a new one
            col = lanes.index(None) if None in lanes else len(lanes)
            if col == len(lanes):
                lanes.append(c.id)
            else:
                lanes[col] = c.id
            matches = [col]
        col, extra = matches[0], matches[1:]

        # Branches forking at this commit join back in just above it.
        if extra:
            rows.append(GraphRow(_join_row(lanes, col, set(extra)), None))
            for i in extra:
                lanes[i] = None
            while lanes and lanes[-1] is None:
                lanes.pop()

        rows.append(GraphRow(_lane_row(lanes, star=col), c))
        lanes[col] = c.parent
        while lanes and lanes[-1] is None:
            lanes.pop()

    return rows


def _lane_row(lanes: list[str | None], star: int) -> str:
    cells = ["*" if i == star else ("│" if lane is not None else " ") for i, lane in enumerate(lanes)]
    return " ".join(cells)


def _join_row(lanes: list[str | None], col: int, extra: set[int]) -> str:
    """Draw lanes in `extra` merging back into `col`, e.g. `├─┴─┘`."""
    last = max(extra)
    out = []
    for i, lane in enumerate(lanes):
        if i == col:
            out.append("├")
        elif i in extra:
            out.append("┘" if i == last else "┴")
        elif col < i < last:
            out.append("┼" if lane is not None else "─")
        else:
            out.append("│" if lane is not None else " ")
        if i < len(lanes) - 1:
            out.append("─" if col <= i < last else " ")
    return "".join(out).rstrip()
