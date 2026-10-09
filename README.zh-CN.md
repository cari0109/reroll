# LifeGit

[English](README.md) | **简体中文**

> `git log --graph`，但管理的是你的人生。

每个决定是一次 commit，"如果当初……"是一条 branch，未来是尚未坍缩的叠加态。

**仅供娱乐，不构成任何预测或建议。**

🚧 开发中。

## 快速开始

```bash
pip install -e .
life init --lang zh    # 中文
life init              # English（默认）
life commit            # 面对一个决定，做出选择
life log               # 查看历史，包括没选的"幽灵"选项
life status            # 当前状态和活跃标签
life checkout -b 如果当初 <commit>  # 回到过去任意一天，换一条路走
life log --graph       # 所有时间线，git 风格
life branch            # 列出你的平行人生
```

## 开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
