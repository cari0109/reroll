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
