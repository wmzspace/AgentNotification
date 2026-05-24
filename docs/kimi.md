# Kimi Code CLI

> 2026-05 起,[Kimi Code CLI](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html) 已经支持 Claude 风格的 hook 机制(`Stop` / `Notification` / `PreToolUse` 等共 13 个事件)。本工具直接走原生 hook,不再需要 wrapper。
>
> 如果你装的是更早不带 hook 的 Kimi(老 `kimi-cli`),仍可以用 `agentnotify wrap` 包一层 — 见文末。

## 自动配置

```bash
agentnotify init
```

在 agent 多选环节勾上 **Kimi Code** 即可。`agentnotify` 会:

- 备份原 `~/.kimi/config.toml` 到同目录:`config.toml.agentnotify-bak-<时间戳>`
- 用 `tomllib` 解析现有 `hooks = [...]` 数组,合并/追加 Stop + Notification 两个 inline-table 条目(用户自己写的 hook 全部保留)
- `command` 字段写**绝对路径**(取当前 `agentnotify` 入口),避免 Kimi 子进程 PATH 不全
- 兜底:检测到旧版本工具留下的 `[[hooks]]` array-of-tables 块会自动清理 — 它们会让 TOML 整体非法
- 幂等:Stop + Notification 都已存在且路径已对就 ALREADY_PRESENT

## 手动配置

在 `~/.kimi/config.toml` 顶部已有 `hooks = []`(Kimi 1.44+ 默认写入)。**修改这一行**为 inline-table 数组,不要追加 `[[hooks]]` 表:

```toml
hooks = [
    { event = "Stop", command = "/abs/path/to/agentnotify hook kimi-stop 2>/dev/null || true", timeout = 10 },
    { event = "Notification", command = "/abs/path/to/agentnotify hook kimi-notification 2>/dev/null || true", timeout = 10 },
]
```

> ⚠️ 不要写 `[[hooks]]` array-of-tables 头。`hooks = []` 已经把 `hooks` 声明成了普通 scalar / inline array,TOML 规范禁止同一个 key 既是 scalar 又是 array-of-tables,Kimi 会拒绝启动并报 `Invalid TOML: Key "hooks" already exists`。
>
> 用绝对路径(`which agentnotify` 拿)。Kimi spawn hook 子进程时的 PATH 不一定包含 conda/pyenv 激活路径,裸 `agentnotify` 加 `|| true` 会让失败完全静默。

## 行为

- **Stop hook**:每次 turn 结束触发。Kimi 的 Stop payload 不带 transcript 路径,所以推送内容固定为 `Kimi 完成 / 回答完成`。如果将来 Kimi 在 payload 里加了 last-assistant-message,在 `agentnotify/hooks.py:kimi_stop` 里读出来即可。
- **Notification hook**:Kimi 通过 sink 路由通知(权限请求、subagent 完成等)。`agentnotify` 直接转发 `title` 和 `body` 字段;`body` 为空的事件会被静默过滤(避免空通知)。

## 排错

```bash
echo '{"session_id":"x","cwd":"/y","hook_event_name":"Stop"}' \
  | agentnotify hook kimi-stop --dry-run
```

想看 Kimi 实际发的 payload,把 `command` 临时改成 `tee /tmp/kimi-hook.json | agentnotify hook kimi-stop`。

## 老版本 Kimi(无 hook)

如果你的 Kimi 不支持 hook,退回 wrapper 路线:

```bash
agentnotify wrap --label "kimi-重构" -- kimi --task "重构 storage 模块"
```

加 shell alias 让交互模式也响铃:

```bash
# ~/.bashrc 或 ~/.zshrc
alias kimi='agentnotify wrap --label kimi -- kimi'
```
