"""Narration layer: writes decision prompts, option labels, and commentary.

The narrator may only pick actions from the action table; it never decides
numbers. Milestone 2 adds an implementation backed by Claude.
"""

from __future__ import annotations

import random
import re
from typing import Protocol

from pydantic import BaseModel, Field

from reroll.i18n import Lang, LocalizedText, t
from reroll.models import Commit, Risk, State, Tag


class OptionDraft(BaseModel):
    label: str
    action: str


class Proposal(BaseModel):
    decision: str
    options: list[OptionDraft] = Field(min_length=2, max_length=4)


class NarratorContext(BaseModel):
    """Full context is passed on every call; the narrator isn't expected to remember anything."""

    lang: Lang
    day: int
    state: State
    tags: list[Tag]
    recent: list[str]
    actions: dict[str, str]


class Narrator(Protocol):
    def propose(self, ctx: NarratorContext, decision: str | None = None) -> Proposal: ...

    def narrate(self, ctx: NarratorContext, commit: Commit) -> str: ...

    def classify(self, ctx: NarratorContext, decision: str, labels: list[str]) -> list[str | None]:
        """Guess an action type for each user-written option label; None when unsure."""
        ...


def format_effects(effects: dict[str, int], lang: Lang) -> str:
    parts = [f"{t(f'stat.{k}', lang)} {v:+d}" for k, v in effects.items() if v]
    return ", ".join(parts) or t("effects.none", lang)


# ---------------------------------------------------------------- mock


def _lt(en: str, zh: str) -> LocalizedText:
    return LocalizedText(en=en, zh=zh)


SCENARIOS: list[tuple[LocalizedText, list[tuple[LocalizedText, str]]]] = [
    (
        _lt("Gym tonight, or stay late at work?", "今晚去健身还是加班？"),
        [(_lt("Hit the gym", "去健身"), "exercise"), (_lt("Stay late", "留下来加班"), "overtime")],
    ),
    (
        _lt("It's 1 a.m. One more episode?", "已经凌晨一点了，再看一集吗？"),
        [(_lt("One more episode", "再看一集"), "stay_up"), (_lt("Lights out", "关灯睡觉"), "rest")],
    ),
    (
        _lt("Friends invited you to hotpot on Friday night", "朋友约周五晚上吃火锅"),
        [
            (_lt("I'm in!", "去！"), "socialize"),
            (_lt("Cook at home and save", "在家做饭省钱"), "save_money"),
            (_lt("Stay in and study", "在家学习"), "study"),
        ],
    ),
    (
        _lt("That thing in your cart just went on sale", "购物车里那件东西打折了"),
        [(_lt("Buy it", "下单"), "impulse_buy"), (_lt("Empty the cart", "清空购物车"), "save_money")],
    ),
    (
        _lt("How should you spend Saturday morning?", "周六上午怎么过？"),
        [
            (_lt("Learn something new", "学点新东西"), "study"),
            (_lt("Sleep till noon", "睡到中午"), "rest"),
            (_lt("Go for a run", "出门跑步"), "exercise"),
        ],
    ),
]

# One pattern per action covering both languages, so matching doesn't depend on repo language.
KEYWORDS: dict[str, re.Pattern[str]] = {
    action: re.compile(pattern, re.IGNORECASE)
    for action, pattern in {
        "exercise": r"健身|运动|跑步|锻炼|散步|爬山|游泳|瑜伽|骑车|打球|马拉松|\b(gym|work ?out|exercis(e|ing)|run(ning)?|jog(ging)?|walk(ing)?|hik(e|ing)|swim(ming)?|yoga|bik(e|ing)|cycling)\b",
        "overtime": r"加班|工作|项目上线|开会|\b(overtime|work late|extra work|deadline|meeting|report)\b",
        "stay_up": r"熬夜|游戏|追剧|刷手机|再看|\b(stay(ing)? up|all-nighter|games?|gaming|binge|one more episode|scroll(ing)?)\b",
        "socialize": r"聚|朋友|约|饭局|社交|吃饭|同事|电话|家人|爸妈|妈妈|KTV|\b(friends?|party|hang ?out|drinks|call (my )?(mom|dad|parents|family))\b",
        "impulse_buy": r"买|购|下单|剁手|逛街|商场|\b(buy|shop(ping)?|order|sale|splurge)\b",
        "save_money": r"省|存钱|攒|做饭|带饭|\b(sav(e|ing)|budget|cook(ing)?|meal prep)\b",
        "study": r"学|读书|看书|课|刷题|练琴|吉他|写代码|编程|自习|图书馆|\b(study|learn(ing)?|read(ing)?|course|leetcode|side project|practi[cs]e|code|coding)\b",
        "rest": r"睡|休息|躺|宅|放松|\b(sleep(ing)?|rest|nap|relax|chill|stay home)\b",
    }.items()
}

def match_action(text: str, allowed: dict[str, str] | list[str]) -> str | None:
    """First action whose keywords appear in `text`, or None."""
    return next((a for a, pat in KEYWORDS.items() if a in allowed and pat.search(text)), None)


LABELS: dict[str, LocalizedText] = {
    "exercise": _lt("Work out", "去运动"),
    "overtime": _lt("Get some work done", "去工作"),
    "stay_up": _lt("Stay up late", "熬个夜"),
    "socialize": _lt("Go out with friends", "和朋友出去"),
    "save_money": _lt("Save money", "省着点"),
    "impulse_buy": _lt("Treat yourself", "买买买"),
    "study": _lt("Study", "学习"),
    "rest": _lt("Get some rest", "好好休息"),
}

QUIPS: dict[Risk, dict[Lang, list[str]]] = {
    "low": {
        "en": [
            "Safe route. The commentator yawns.",
            "Textbook play. Nothing to roast here.",
            "Playing it safe. Chat: 'that's it?'",
        ],
        "zh": ["稳健路线，解说员打了个哈欠。", "教科书式操作，没什么好吐槽的。", "安全牌。观众：就这？"],
    },
    "medium": {
        "en": [
            "Getting risky. The crowd sits up.",
            "Bold route... the commentator reserves judgment.",
            "Health bar turning yellow. Watch your footing.",
        ],
        "zh": ["有点冒险了，观众开始坐直身子。", "这条路线……解说员保留意见。", "血条开始泛黄，注意走位。"],
    },
    "high": {
        "en": [
            "Danger! Only speedrunners take this line.",
            "The commentator is already scouting your respawn point.",
            "Red HP and still showing off. Is this what life is?",
        ],
        "zh": ["危！这是速通选手才敢走的路线。", "解说员已经开始帮你找复活点了。", "红血了还在浪，这就是人生吗？"],
    },
}

NARRATION: dict[Lang, str] = {
    "en": "Day {day}: the runner picks “{label}” ({effects}). {quip}",
    "zh": "Day {day}，选手选择了「{label}」（{effects}）。{quip}",
}


class MockNarrator:
    """Narrator that calls no model: preset scenarios, keyword matching, template quips.
    Fully deterministic."""

    def propose(self, ctx: NarratorContext, decision: str | None = None) -> Proposal:
        if decision is None:
            text, opts = SCENARIOS[(ctx.day - 1) % len(SCENARIOS)]
            return Proposal(
                decision=text.get(ctx.lang),
                options=[OptionDraft(label=label.get(ctx.lang), action=a) for label, a in opts],
            )

        actions = [a for a, pat in KEYWORDS.items() if pat.search(decision) and a in ctx.actions]
        for fallback in ("rest", "stay_up", "study"):
            if len(actions) >= 2:
                break
            if fallback not in actions and fallback in ctx.actions:
                actions.append(fallback)
        return Proposal(
            decision=decision,
            options=[
                OptionDraft(label=LABELS[a].get(ctx.lang) if a in LABELS else a, action=a)
                for a in actions[:4]
            ],
        )

    def classify(self, ctx: NarratorContext, decision: str, labels: list[str]) -> list[str | None]:
        return [match_action(label, ctx.actions) for label in labels]

    def narrate(self, ctx: NarratorContext, commit: Commit) -> str:
        opt = commit.chosen_option
        quip = random.Random(commit.id).choice(QUIPS[commit.risk][ctx.lang])
        return NARRATION[ctx.lang].format(
            day=commit.day, label=opt.label, effects=format_effects(opt.effects, ctx.lang), quip=quip
        )
