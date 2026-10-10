# Reroll

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
life status            # 当前状态、活跃标签和未来走向
life forecast -d 30    # 模拟 200 个平行未来，画成概率带
life checkout -b 如果当初 <commit>  # 回到过去任意一天，换一条路走
life whatif <commit>   # 如果当初选了另一个呢？
life log --graph       # 所有时间线，git 风格
life branch            # 列出你的平行人生
```

## AI 解说员（可选）

配置 Anthropic 凭证后，决策、选项和解说都由 Claude 来写：

```bash
export ANTHROPIC_API_KEY=...        # https://console.anthropic.com
export REROLL_MODEL=claude-opus-5-5 # 可选，默认就是这个
export REROLL_NARRATOR=mock         # 可选：强制使用离线解说员
```

没有凭证时 Reroll 完全离线运行，使用内置解说员。Claude 不碰任何数值：它只能从
`params.yaml` 里选行为类型，具体效果由规则引擎决定。

## 开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
