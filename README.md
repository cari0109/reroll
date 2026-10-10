# Reroll

**English** | [简体中文](README.zh-CN.md)

> `git log --graph`, but for your life.

Every decision is a commit. Every "what if" is a branch. The future is a superposition that hasn't collapsed yet.

**For entertainment only. Not a prediction or advice.**

🚧 Work in progress.

## Quick start

```bash
pip install -e .
life init              # English (default)
life init --lang zh    # 中文
life commit            # face a decision, make a choice
life log               # history, including the ghosts of choices you didn't make
life status            # current stats and active tags
life checkout -b what-if <commit>   # rewind to any past day and try another path
life whatif <commit>   # what if you'd picked the other option back then?
life log --graph       # every timeline, git-style
life branch            # list your parallel lives
```

## AI narrator (optional)

With Anthropic credentials, Claude writes the decisions, options and commentary:

```bash
export ANTHROPIC_API_KEY=...        # https://console.anthropic.com
export REROLL_MODEL=claude-opus-5-5 # optional, this is the default
export REROLL_NARRATOR=mock         # optional: force the offline narrator
```

Without credentials Reroll runs fully offline with a built-in narrator. Claude never
touches the numbers: it can only pick an action type from `params.yaml`, and the rules
engine rolls the effects.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
