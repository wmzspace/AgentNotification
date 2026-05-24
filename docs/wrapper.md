# 通用 wrapper：`agentnotify wrap`

任何 CLI（没有原生 hook 的 agent、批量脚本、长跑训练任务）都能用这个套一层。

## 基本用法

```bash
agentnotify wrap -- mycmd arg1 arg2
agentnotify wrap --label "训练" -- python train.py --epochs 200
agentnotify wrap codex exec "do stuff"   # 前导 `--` 可省略
```

`--` 用来分隔 `agentnotify` 自己的选项和被包命令的参数，建议保留以避免歧义（比如被包命令也带 `--label`）。

## 行为

- 子进程 **stdout / stderr 不被吞**，原样输出到终端。
- 子进程退出码 **原样透传**，wrapper 自身退出码 = 子进程退出码。
- 退出时单次推送：
  - exit 0：标题 `<label> 完成`，正文 `用时 N.Ns · exit 0`
  - 非 0：标题 `<label> 失败`，正文 `exit N · 用时 N.Ns`
- 找不到可执行文件：wrapper 返回 127 并打印错误。

## 何时用 wrap、何时用原生 hook

| 场景 | 推荐 |
|------|------|
| Claude Code / Codex 8+ / Kimi Code 1.44+ | 原生 hook（更细粒度，turn 级别 — 见各自 docs） |
| 老版本 Kimi(`kimi-cli`,无 hook) | `wrap` |
| 没有 hook 机制的第三方 agent CLI | `wrap` |
| 一次性脚本：构建、训练、爬取 | `wrap` |
| 你想包整个 `agent --interactive` REPL | `wrap` 或 shell alias |

## 在 Makefile / shell pipeline 里

```makefile
train:
	agentnotify wrap --label "train" -- python train.py
```

```bash
# 串多个长任务，最后一次推送即可
agentnotify wrap --label "全流程" -- bash -c "
    python prep.py && python train.py && python eval.py
"
```

## 静默推送

wrap 走的是 hook 模式（quiet=True），所以推送本身不会污染 stdout。只有推送 **失败** 时才会在 stderr 留一行诊断。
