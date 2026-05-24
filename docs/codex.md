# OpenAI Codex CLI

> Codex 8+ 已经从单一 `notify = [...]` 字段升级到 Claude/Kimi 风格的 `[[hooks.<Event>]]` 表。本工具默认走新 hooks 接口,旧 `notify` 仅作向后兼容。
>
> **关键 feature flag**:Codex 0.133+ 必须在 `[features]` 表里写 `hooks = true` hooks 才会被事件层调用;旧名字 `codex_hooks = true` 已 deprecated 且**不再被识别**,即使你的 `[[hooks.Stop]]` 表合法、Codex 在 `[hooks.state]` 里写了 `trusted_hash`,事件依然不会路由进来。`agentnotify init` 会自动重命名 / 删除这个废弃别名。

## 自动配置

```bash
agentnotify init
```

在 agent 多选环节勾上 **Codex CLI** 即可。`agentnotify` 会:

- 备份原 `~/.codex/config.toml` 到同目录:`config.toml.agentnotify-bak-<时间戳>`
- 在 `[features]` 表确保 `hooks = true`(必要时新建 `[features]`,删除废弃的 `codex_hooks`)
- 追加两段 array-of-tables 到文件末尾:
  - `[[hooks.Stop]]` — turn 结束触发,推送回答摘要
  - `[[hooks.PermissionRequest]]` — Codex 要求批准工具调用时触发,推送工具名+描述
- `command` 字段写**绝对路径**(取当前 `agentnotify` 入口),避免 Codex 子进程 PATH 不全找不到二进制
- 幂等:检测到 `hook codex-stop` / `codex-permission` 字符串就跳过追加;命令路径已对、features 已对就 ALREADY_PRESENT

注入后用 `python3 -c "import tomllib,pathlib; print(tomllib.loads(pathlib.Path('~/.codex/config.toml').expanduser().read_text()))"` 可以验证 TOML 仍然合法。

## 手动配置

如果你想自己写,在 `~/.codex/config.toml` **末尾**追加:

```toml
[features]
hooks = true   # 关键 — 没这行 hooks 不会触发

[[hooks.Stop]]

[[hooks.Stop.hooks]]
type = "command"
command = "/abs/path/to/agentnotify hook codex-stop 2>/dev/null || true"
timeout = 30

[[hooks.PermissionRequest]]

[[hooks.PermissionRequest.hooks]]
type = "command"
command = "/abs/path/to/agentnotify hook codex-permission 2>/dev/null || true"
timeout = 30
```

> ⚠️ array-of-tables 一定要放在所有 `[table]` / `[[array.table]]` 块之后,不然会被前面的表头吞掉作用域。在文件末尾追加最安全。
>
> `command` 用绝对路径(`which agentnotify` 或 `command -v agentnotify` 拿)。Codex 启动 hook 子进程时不继承 conda/pyenv 的 activate 状态,裸 `agentnotify` 多半找不到,而命令里又加了 `|| true` 吞错,失败完全静默,排查起来很坑。

## 行为

- **Stop hook** payload(stdin JSON):
  ```json
  {
    "session_id": "...", "transcript_path": "...", "cwd": "...",
    "hook_event_name": "Stop", "model": "...", "permission_mode": "...",
    "turn_id": "...", "stop_hook_active": false,
    "last_assistant_message": "..."
  }
  ```
  `agentnotify` 把 `last_assistant_message` 按句号/空格回退截断到 120 字符做正文。空消息时正文为「回答完成」。

- **PermissionRequest hook** payload:
  ```json
  {
    "tool_name": "Bash",
    "tool_input": { "description": "rm -rf /tmp/x", "command": "..." },
    ...
  }
  ```
  推送标题固定 `Codex 需要权限`,正文 `<tool_name>: <description>`。

## 排错

dry-run 测 Stop 解析:

```bash
echo '{"hook_event_name":"Stop","last_assistant_message":"重构完成"}' \
  | agentnotify hook codex-stop --dry-run
```

dry-run 测 PermissionRequest:

```bash
echo '{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"description":"rm -rf"}}' \
  | agentnotify hook codex-permission --dry-run
```

想看 Codex 实际发的 payload,临时把 command 改成 `tee /tmp/codex-hook.json | agentnotify hook codex-stop`。

## 配置正确但 hook 不响?核对清单

按这个顺序排查:

1. `~/.codex/config.toml` 里 `[features]` 段下有 `hooks = true`(**不是** `codex_hooks = true`,后者已废弃)
2. `command` 是绝对路径,不是裸 `agentnotify`
3. 命令本身能跑:`/abs/path/to/agentnotify send "test" "hello"` 真的响铃
4. 重启 Codex CLI(它启动时读 config.toml,改完不重启不生效)
5. `~/.codex/config.toml` 末尾的 `[hooks.state]` 表里能看到对应的 `trusted_hash` — 说明 Codex 至少扫到并信任了 hook
6. `agentnotify init --force` 重跑一次让 codex 这一项重新对齐;只要勾 Codex CLI 一项,其他都跳过

## 旧的 `notify = [...]` 方式

Codex 早期版本只有顶层 `notify`,通过 argv 而非 stdin 接 payload:

```toml
notify = ["agentnotify", "hook", "codex"]
```

此机制仍可工作,但当 `[features].hooks` 启用(默认)后,Codex 内部事件流走 hooks 路径,旧 `notify` 不再被某些事件触发——这就是为什么"以前能响,升级后没动静"。新装机请用上面的 `[[hooks.Stop]]` 形式。
