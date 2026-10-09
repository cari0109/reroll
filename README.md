# LifeGit

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
life log --graph       # every timeline, git-style
life branch            # list your parallel lives
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
