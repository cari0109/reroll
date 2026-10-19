"""Offline commentary: what the built-in narrator says after a choice.

Without an LLM we still want commentary that reacts to *this* run, not a random line per risk
level. Each choice produces a few candidate "beats" (a habit streak, a stat in the red, a
recovery, yesterday's aftershock, a ghost that would have done better, a big swing); the most
interesting one is used, followed by a short quip about the risk. Deterministic per commit.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from reroll import rules
from reroll.i18n import Lang, t
from reroll.models import Commit, Risk
from reroll.params import Params, default_params
from reroll.sim import RISK_STATS

if TYPE_CHECKING:  # avoids a circular import with narrator.py
    from reroll.narrator import NarratorContext

LOW_BELOW = 30          # a survival stat under this is worth calling out
RECOVERY_GAIN = 8       # a stat that was low and rose at least this much
SWING = 10              # a single change at least this big
GHOST_EDGE = 5          # a skipped option that would have been at least this much better
GHOST_CARES_BELOW = 50  # ...measured on a stat that is actually under pressure

QUIPS: dict[Risk, dict[Lang, list[str]]] = {
    "low": {
        "en": ["Safe route. The commentator yawns.", "Textbook play.", "Playing it safe. Chat: “that's it?”"],
        "zh": ["稳健路线，解说员打了个哈欠。", "教科书式操作。", "安全牌。观众：就这？"],
    },
    "medium": {
        "en": ["The crowd sits up.", "The commentator reserves judgment.", "Health bar turning yellow. Watch your footing."],
        "zh": ["观众开始坐直身子。", "解说员保留意见。", "血条开始泛黄，注意走位。"],
    },
    "high": {
        "en": ["Only speedrunners take this line.", "The commentator is scouting your respawn point.", "Red HP and still showing off."],
        "zh": ["这是速通选手才敢走的路线。", "解说员已经开始帮你找复活点了。", "红血了还在浪，这就是人生吗？"],
    },
}

OPENER: dict[Lang, str] = {
    "en": "Day {day}: the runner picks “{label}”.",
    "zh": "Day {day}，选手选择了「{label}」。",
}

STREAK: dict[str, dict[Lang, list[str]]] = {
    "late_night": {"en": ["Night {n} in a row of staying up.", "That's {n} late nights straight."],
                   "zh": ["连续第 {n} 晚熬夜了。", "熬夜已经是第 {n} 晚。"]},
    "exercised": {"en": ["Workout {n} in a row. A habit is forming."], "zh": ["连续第 {n} 次运动，习惯正在养成。"]},
    "studied": {"en": ["Study session {n} in a row. The skill tree is lighting up."], "zh": ["连续第 {n} 次学习，技能树在点亮。"]},
    "socialized": {"en": ["Out with people {n} times lately. The social bar says thanks."], "zh": ["最近第 {n} 次社交，社交条在感谢你。"]},
    "frugal": {"en": ["Frugal streak: {n}. The wallet is healing."], "zh": ["连续第 {n} 次省钱，钱包正在回血。"]},
    "impulse_spent": {"en": ["Purchase number {n} this week. The cart remembers."], "zh": ["这周第 {n} 次剁手，购物车都记得。"]},
    "overtime": {"en": ["Overtime, round {n}. The office knows your name."], "zh": ["连续第 {n} 次加班，工位都认识你了。"]},
    "rested": {"en": ["Rest day number {n}. Recharging, or just comfy?"], "zh": ["连续第 {n} 次休息，是在充电还是在躺平？"]},
}

LOW: dict[Lang, list[str]] = {
    "en": ["{stat} is down to {v}.", "{stat} at {v}: the bar is blinking red."],
    "zh": ["{stat}只剩 {v} 了。", "{stat}掉到 {v}，血条在闪红。"],
}
RECOVERY: dict[Lang, list[str]] = {
    "en": ["{stat} climbs back to {v}. Back from the brink."],
    "zh": ["{stat}回到 {v}，从悬崖边拉回来了。"],
}
AFTERSHOCK: dict[Lang, list[str]] = {
    "en": ["Recent habits still cost {fx} this morning."],
    "zh": ["前几天的习惯今天早上还在扣：{fx}。"],
}
SWING_TEXT: dict[Lang, list[str]] = {
    "en": ["{stat} {d} in one go."],
    "zh": ["{stat}一口气 {d}。"],
}
GHOST_BETTER: dict[Lang, list[str]] = {
    "en": ["“{ghost}” would have left {stat} at {v}, not {now}.", "The ghost of “{ghost}” had {stat} at {v}, not {now}."],
    "zh": ["选「{ghost}」的话，{stat}会是 {v}，而不是 {now}。", "「{ghost}」的幽灵里，{stat}是 {v}，不是 {now}。"],
}
GHOST_PLAIN: dict[Lang, list[str]] = {
    "en": ["“{ghost}” was right there.", "The ghost of “{ghost}” is watching."],
    "zh": ["「{ghost}」那条路就在旁边。", "「{ghost}」的幽灵在看着你。"],
}


def _fx(changes: dict[str, int], lang: Lang) -> str:
    return ", ".join(f"{t(f'stat.{k}', lang)} {v:+d}" for k, v in changes.items())


def commentary(ctx: "NarratorContext", commit: Commit, params: Params | None = None) -> str:
    params = params or default_params()
    lang = ctx.lang
    rng = random.Random(commit.id)
    say = lambda table, **kw: rng.choice(table[lang]).format(**kw)  # noqa: E731
    name = lambda stat: t(f"stat.{stat}", lang)  # noqa: E731
    chosen = commit.chosen_option
    after = commit.state_after
    beats: list[tuple[float, str]] = []

    # a habit that keeps coming back
    for spec in params.actions[chosen.action].tags:
        tag = next((x for x in commit.tags_active if x.name == spec.name), None)
        if tag and tag.count >= 2 and spec.name in STREAK:
            beats.append((3 + tag.count, rng.choice(STREAK[spec.name][lang]).format(n=tag.count)))

    # the weakest survival stat, if it's in trouble
    weakest = min(RISK_STATS, key=lambda s: getattr(after, s))
    low_v = getattr(after, weakest)
    if low_v < LOW_BELOW:
        beats.append((6 if low_v < 20 else 4, say(LOW, stat=name(weakest), v=low_v)))

    # climbing out of a hole
    for s in RISK_STATS:
        before, now = getattr(ctx.state, s), getattr(after, s)
        if before < LOW_BELOW and now >= before + RECOVERY_GAIN:
            beats.append((5, say(RECOVERY, stat=name(s), v=now)))

    # yesterday's habits still charging interest (tag part of the start-of-day change)
    hurt = {k: v - params.daily_drift.get(k, 0) for k, v in commit.carryover.items()}
    hurt = {k: v for k, v in hurt.items() if v <= -3}
    if hurt:
        beats.append((3.5, say(AFTERSHOCK, fx=_fx(hurt, lang))))

    # one big swing
    if chosen.effects:
        stat, d = max(chosen.effects.items(), key=lambda kv: abs(kv[1]))
        if abs(d) >= SWING:
            beats.append((2.5, say(SWING_TEXT, stat=name(stat), d=f"{d:+d}")))

    # the road not taken, measured on the stat that needs it most
    ghosts = [o for o in commit.options if o.id != commit.chosen]
    if ghosts:
        start = rules.apply_effects(ctx.state, commit.carryover, params.stats)
        value = lambda o: getattr(rules.apply_effects(start, o.effects, params.stats), weakest)  # noqa: E731
        best = max(ghosts, key=value)
        edge = value(best) - low_v
        if edge >= GHOST_EDGE and low_v < GHOST_CARES_BELOW:
            text = say(GHOST_BETTER, ghost=best.label, stat=name(weakest), v=value(best), now=low_v)
            beats.append(((4 if low_v < 40 else 2) + edge / 10, text))
        else:
            beats.append((1, say(GHOST_PLAIN, ghost=rng.choice(ghosts).label)))

    beat = max(beats, key=lambda b: b[0])[1] if beats else ""
    beat = beat[:1].upper() + beat[1:]  # English beats may start with a stat name
    parts = [OPENER[lang].format(day=commit.day, label=chosen.label), beat, rng.choice(QUIPS[commit.risk][lang])]
    return ("" if lang == "zh" else " ").join(p for p in parts if p)
