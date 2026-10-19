"""Offline decision prompts: the questions the built-in narrator asks when no LLM is available.

Each scenario has a `fits` function that says how much more likely it is in the current
situation (tired people get asked about sleep, a late-night streak gets called out). Recently
asked questions are strongly avoided, so a week of play rarely repeats.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from reroll.i18n import LocalizedText
from reroll.models import StatName

if TYPE_CHECKING:  # avoids a circular import with narrator.py
    from reroll.narrator import NarratorContext


def _lt(en: str, zh: str) -> LocalizedText:
    return LocalizedText(en=en, zh=zh)


Fit = Callable[["NarratorContext"], float]


def always(_: "NarratorContext") -> float:
    return 1.0


def low(stat: StatName, below: int, boost: float = 5.0, otherwise: float = 1.0) -> Fit:
    """More likely when `stat` is low. Questions that state the condition ("you're exhausted")
    pass a small `otherwise` so they rarely show up when it isn't true."""
    return lambda ctx: boost if getattr(ctx.state, stat) < below else otherwise


def high(stat: StatName, above: int, boost: float = 3.0) -> Fit:
    return lambda ctx: boost if getattr(ctx.state, stat) > above else 1.0


def tagged(name: str, boost: float = 6.0, otherwise: float = 0.3) -> Fit:
    """Likely while the tag is active, rare otherwise (the question wouldn't make sense)."""
    return lambda ctx: boost if any(t.name == name for t in ctx.tags) else otherwise


@dataclass(frozen=True)
class Scenario:
    question: LocalizedText
    options: list[tuple[LocalizedText, str]]  # (label, action type)
    fits: Fit = always


SCENARIOS: list[Scenario] = [
    # Day 1 is always the first one: every new life starts with the same classic dilemma.
    Scenario(_lt("Gym tonight, or stay late at work?", "今晚去健身还是加班？"),
             [(_lt("Hit the gym", "去健身"), "exercise"), (_lt("Stay late", "留下来加班"), "overtime")]),
    Scenario(_lt("It's 1 a.m. One more episode?", "已经凌晨一点了，再看一集吗？"),
             [(_lt("One more episode", "再看一集"), "stay_up"), (_lt("Lights out", "关灯睡觉"), "rest")],
             high("energy", 55, 2.0)),
    Scenario(_lt("Friends invited you to hotpot on Friday night", "朋友约周五晚上吃火锅"),
             [(_lt("I'm in!", "去！"), "socialize"), (_lt("Cook at home and save", "在家做饭省钱"), "save_money"),
              (_lt("Stay in and study", "在家学习"), "study")],
             low("social", 45, 3.0)),
    Scenario(_lt("That thing in your cart just went on sale", "购物车里那件东西打折了"),
             [(_lt("Buy it", "下单"), "impulse_buy"), (_lt("Empty the cart", "清空购物车"), "save_money")],
             high("money", 50, 2.0)),
    Scenario(_lt("How should you spend Saturday morning?", "周六上午怎么过？"),
             [(_lt("Learn something new", "学点新东西"), "study"), (_lt("Sleep till noon", "睡到中午"), "rest"),
              (_lt("Go for a run", "出门跑步"), "exercise")]),
    Scenario(_lt("6 p.m. Your manager asks for a quick favor", "下午六点，领导说「帮个小忙」"),
             [(_lt("Sure, I'll stay", "好，我留下"), "overtime"), (_lt("Log off", "下班回家"), "rest"),
              (_lt("Gym instead", "转身去健身"), "exercise")]),
    Scenario(_lt("Rent is due. There's a concert this weekend", "要交房租了，周末还有场演唱会"),
             [(_lt("Buy the ticket", "买票！"), "impulse_buy"), (_lt("Skip it, save", "忍住，存钱"), "save_money"),
              (_lt("Friends over instead", "叫朋友来家里"), "socialize")],
             low("money", 45, 3.0)),
    Scenario(_lt("A free online course starts tonight", "今晚有个免费网课开课"),
             [(_lt("Join the first class", "去上第一节"), "study"), (_lt("Game until 2 a.m.", "打游戏到两点"), "stay_up")],
             low("goal", 25, 2.5)),
    Scenario(_lt("Your alarm just went off. Snooze?", "闹钟响了。再睡五分钟？"),
             [(_lt("Snooze. Again.", "再睡一会儿"), "rest"), (_lt("Morning run", "起来晨跑"), "exercise"),
              (_lt("Read before work", "上班前看会儿书"), "study")],
             low("energy", 40, 4.0)),
    Scenario(_lt("An old friend texts: drinks tonight?", "很久没见的朋友发消息：今晚喝一杯？"),
             [(_lt("Absolutely", "当然去"), "socialize"), (_lt("Rain check, need sleep", "改天吧，要睡觉"), "rest")],
             low("social", 40, 5.0)),
    Scenario(_lt("Payday! What first?", "发工资了！先干嘛？"),
             [(_lt("Move half to savings", "先存一半"), "save_money"), (_lt("Treat yourself", "犒劳一下自己"), "impulse_buy"),
              (_lt("Buy friends dinner", "请朋友吃饭"), "socialize")],
             low("money", 40, 4.0)),
    Scenario(_lt("Your side project has gathered dust for a week", "你的个人项目已经吃灰一周了"),
             [(_lt("Ship one small thing", "今晚推进一小步"), "study"), (_lt("All-night sprint", "通宵冲刺"), "stay_up"),
              (_lt("It can wait", "再放放吧"), "rest")],
             low("goal", 20, 4.0, otherwise=0.4)),
    Scenario(_lt("Another late night in a row. Tonight too?", "已经连续熬夜了，今晚还熬吗？"),
             [(_lt("Just one more hour", "就再玩一小时"), "stay_up"), (_lt("Phone in the drawer, lights out", "手机扔抽屉，关灯"), "rest")],
             tagged("late_night")),
    Scenario(_lt("Rainy Sunday afternoon", "下雨的周日下午"),
             [(_lt("Nap", "睡个午觉"), "rest"), (_lt("Read a book", "看本书"), "study"),
              (_lt("Board games with friends", "约朋友玩桌游"), "socialize")]),
    Scenario(_lt("Coworkers are heading out for karaoke", "同事们要去唱K"),
             [(_lt("Grab the mic", "我也去"), "socialize"), (_lt("Finish that report", "留下写完报告"), "overtime"),
              (_lt("Head home", "回家休息"), "rest")]),
    Scenario(_lt("You're running on fumes", "你的精力快见底了"),
             [(_lt("In bed by 9", "九点就上床"), "rest"), (_lt("Push through, deadline's close", "硬撑，快截止了"), "overtime"),
              (_lt("Takeout and a treat", "点外卖，再买点好吃的"), "impulse_buy")],
             low("energy", 30, 6.0, otherwise=0.05)),
    Scenario(_lt("The gym membership you never use renews tomorrow", "从来没去过的健身卡明天续费"),
             [(_lt("Go tonight to justify it", "今晚就去，回本"), "exercise"), (_lt("Cancel it", "退掉"), "save_money"),
              (_lt("Upgrade to the fancy plan", "升级成高级会员"), "impulse_buy")]),
    Scenario(_lt("Feeling a bit low lately", "最近有点低落"),
             [(_lt("Call an old friend", "给老朋友打个电话"), "socialize"), (_lt("Walk it off", "出去走走"), "exercise"),
              (_lt("Retail therapy", "买点东西治愈一下"), "impulse_buy")],
             low("mood", 35, 6.0, otherwise=0.05)),
    Scenario(_lt("Flash sale ends at midnight", "限时秒杀，午夜结束"),
             [(_lt("Add to cart", "加购物车"), "impulse_buy"), (_lt("Close the tab", "关掉页面"), "save_money"),
              (_lt("Keep browsing “just to look”", "继续刷，「就看看」"), "stay_up")]),
    Scenario(_lt("Big deadline on Friday", "周五有个大截止日期"),
             [(_lt("Start early tonight", "今晚就开工"), "overtime"), (_lt("Learn a tool to go faster", "学个能提速的工具"), "study"),
              (_lt("Trust future you", "相信未来的自己"), "rest")]),
    Scenario(_lt("Friends are planning a weekend trip", "朋友们在计划周末出游"),
             [(_lt("Count me in", "算我一个"), "socialize"), (_lt("Can't afford it, stay home", "钱包不允许，在家待着"), "save_money")],
             high("money", 45, 2.5)),
    Scenario(_lt("Habits are sticking. Keep the streak?", "好习惯正在养成，继续保持吗？"),
             [(_lt("Keep it going", "继续"), "exercise"), (_lt("Earned a rest day", "今天休息一天"), "rest")],
             tagged("exercised", boost=4.0)),
]


def pick(ctx: "NarratorContext") -> Scenario:
    """Choose today's question. Day 1 is fixed; after that, weighted by fit and recency."""
    if ctx.day == 1:
        return SCENARIOS[0]
    seen = " ".join(ctx.recent)
    weights = []
    for sc in SCENARIOS:
        w = sc.fits(ctx)
        if sc.question.get(ctx.lang) in seen:
            w *= 0.03  # asked in the last few days
        weights.append(w)
    # Same situation -> same question, so tests, whatif replays and page reloads agree.
    rng = random.Random(f"{ctx.day}|{ctx.state.model_dump_json()}|{'|'.join(ctx.recent)}|{ctx.lang}")
    return rng.choices(SCENARIOS, weights=weights)[0]
