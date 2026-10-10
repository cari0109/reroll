"""Tiny dictionary-based i18n for user-facing text.

Only display strings are translated. Identifiers (action names, stat keys,
tag names) stay in English everywhere.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Lang = Literal["en", "zh"]
LANGS: tuple[Lang, ...] = ("en", "zh")
DEFAULT_LANG: Lang = "en"


class LocalizedText(BaseModel):
    en: str
    zh: str

    def get(self, lang: Lang) -> str:
        return getattr(self, lang)


MESSAGES: dict[str, dict[Lang, str]] = {
    "disclaimer": {
        "en": "For entertainment only. Not a prediction or advice.",
        "zh": "仅供娱乐，不构成任何预测或建议。",
    },
    "error": {"en": "error:", "zh": "错误："},
    "err.not_found": {
        "en": "{path} not found. Run `life init` first.",
        "zh": "{path} 不存在，先运行 `life init`",
    },
    "err.corrupt": {"en": "{path} is malformed:\n{detail}", "zh": "{path} 格式有误：\n{detail}"},
    "err.ref_unknown": {"en": "unknown branch or commit: {ref}", "zh": "找不到分支或 commit：{ref}"},
    "err.ref_ambiguous": {"en": "{ref} is ambiguous: {matches}", "zh": "{ref} 有歧义，可能是：{matches}"},
    "err.branch_name": {
        "en": "invalid branch name {name!r} (letters, digits, . _ / - only)",
        "zh": "分支名 {name!r} 不合法（只能包含文字、数字和 . _ / -）",
    },
    "err.branch_exists": {"en": "branch {name!r} already exists", "zh": "分支 {name!r} 已存在"},
    "err.branch_unknown": {"en": "no branch named {name!r}", "zh": "没有名为 {name!r} 的分支"},
    "branch.created": {
        "en": "Created branch [bold cyan]{name}[/] at {at}",
        "zh": "已在 {at} 创建分支 [bold cyan]{name}[/]",
    },
    "branch.root": {"en": "the very beginning", "zh": "人生起点"},
    "branch.from": {"en": "forked from {at}", "zh": "分叉自 {at}"},
    "checkout.done": {"en": "Switched to branch [bold cyan]{name}[/]", "zh": "已切换到分支 [bold cyan]{name}[/]"},
    "checkout.already": {"en": "Already on {name}", "zh": "已经在分支 {name} 上"},
    "checkout.rewind": {
        "en": "⏪ Time rewinds to the end of Day {day}. Your next commit is Day {next}.",
        "zh": "⏪ 时间倒流回 Day {day} 结束时，下一次 commit 是 Day {next}。",
    },
    "init.exists": {"en": "{path} already exists", "zh": "{path} 已存在"},
    "init.done": {
        "en": "Initialized empty life repository in [bold]{path}[/]",
        "zh": "已在 [bold]{path}[/] 初始化空的人生仓库",
    },
    "status.header": {
        "en": "On branch [bold cyan]{branch}[/] · up next: [bold]Day {day}[/]",
        "zh": "当前分支 [bold cyan]{branch}[/] · 即将进入 [bold]Day {day}[/]",
    },
    "status.tags": {"en": "Active tags: {tags}", "zh": "活跃标签：{tags}"},
    "tags.none": {"en": "none", "zh": "无"},
    "tags.until": {"en": "until Day {day}", "zh": "至 Day {day}"},
    "commit.prompt": {"en": "Your choice", "zh": "你的选择"},
    "commit.bad_choice": {
        "en": "no option {choice!r}; choose from: {ids}",
        "zh": "没有选项 {choice!r}，可选：{ids}",
    },
    "commit.risk": {"en": "risk", "zh": "风险"},
    "log.empty": {
        "en": "No commits on {branch} yet. Try `life commit`.",
        "zh": "分支 {branch} 还没有任何 commit，试试 `life commit`",
    },
    "log.ghost": {"en": "ghost", "zh": "幽灵"},
    "log.root": {"en": "born", "zh": "出生"},
    "effects.none": {"en": "no change", "zh": "无变化"},
    "stat.energy": {"en": "energy", "zh": "精力"},
    "stat.mood": {"en": "mood", "zh": "心情"},
    "stat.money": {"en": "money", "zh": "财务"},
    "stat.social": {"en": "social", "zh": "社交"},
    "stat.goal": {"en": "goal", "zh": "目标"},
}


def t(key: str, lang: Lang, **kwargs: object) -> str:
    return MESSAGES[key][lang].format(**kwargs)
