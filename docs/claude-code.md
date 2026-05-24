# Claude Code

[Claude Code](https://claude.ai/code) 把"回答完成 / 需要注意 / 工具权限"拆成了三个独立 hook,本工具各对应一个推送 kind:

| Claude hook 事件 | 触发时机 | 对应 agentnotify hook |
|---|---|---|
| `Stop` | 每次 Claude 回答结束 | `agentnotify hook claude-stop` |
| `Notification` | idle prompt / auth success / elicitation 等通知类事件 | `agentnotify hook claude-notification` |
| `PermissionRequest` | 工具调用前出现权限对话框 (Bash / Edit / Write / WebFetch …) | `agentnotify hook claude-permission` |

> Claude 2026 起把权限请求拆到独立的 `PermissionRequest` 事件,payload 直接带 `tool_name` + `tool_input`,信息比 `Notification` (`permission_prompt`) 丰富。本工具让 `PermissionRequest` 独占权限通知,`Notification` 跳过 `permission_prompt` 避免双响。

## 自动配置

```bash
agentnotify init
```

在 agent 多选环节勾上 **Claude Code** 即可。`agentnotify` 会:

- 备份原 `~/.claude/settings.json` 到同目录:`settings.json.agentnotify-bak-<时间戳>`
- 把 Stop + Notification + PermissionRequest 三段 hook **合并**进现有 `"hooks"` 字段(已有的 matcher / 其它 hook 全部保留)
- 新写入的 `command` 用绝对路径(避免 hook 子进程 PATH 不全找不到 `agentnotify`)
- 幂等:逐项检测,缺哪段补哪段;三段都在就 ALREADY_PRESENT 跳过

## 手动配置

编辑 `~/.claude/settings.json`,把下面三段并入 `"hooks"` 字段(已有内容时往里合并而不是覆盖):

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/abs/path/to/agentnotify hook claude-stop 2>/dev/null || true",
            "async": true
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/abs/path/to/agentnotify hook claude-notification 2>/dev/null || true",
            "async": true
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/abs/path/to/agentnotify hook claude-permission 2>/dev/null || true",
            "async": true
          }
        ]
      }
    ]
  }
}
```

`matcher: ""` 意为匹配所有事件 — Notification 不限 notification_type,PermissionRequest 不限工具名。如果只想监听特定工具(比如只关心 Bash 权限),把 PermissionRequest 的 matcher 改成 `"Bash"` 或 `"Bash|Edit|Write"`(同 PreToolUse 规则)。

几个细节:

- `async: true` 让推送在后台跑,不卡 Claude 的下一步。
- `2>/dev/null || true` 是双保险 — `agentnotify hook` 本身就已经在配置缺失/网络失败时返回 0,这一层只是防止任何意外的解释器报错冒到 Claude UI。
- 绝对路径:`which agentnotify` 拿,或者运行 `agentnotify init` 让它自动写入(本工具会用当前入口的真实路径)。

## 行为

- **Stop hook**:每次 Claude 回答结束触发。`agentnotify` 解析 `transcript_path`(JSONL,Claude 2026 schema)从尾部往前找最后一条 `type:"assistant"` 且带 text block 的消息(跳过中间只含 `tool_use` / `thinking` 的过渡消息),按句号/空格回退截断到 120 字符作为推送正文。
- **Notification hook**:转发非权限类通知(idle prompt / auth success / elicitation 等)。自动跳过 `permission_prompt`(由 PermissionRequest 独占),也跳过 `waiting for your input`(由 Stop hook 覆盖),避免重复推送。若 payload 带 `title` 字段,推送标题前缀化为 `Claude Code · <title>`。
- **PermissionRequest hook**:权限对话框出现时触发。从 `tool_input` 里依次找 `command` / `file_path` / `path` / `url` / `description` 第一个非空字段拼到 tool 名后面,例如:
  - Bash → `Bash: rm -rf /tmp/x`
  - Write → `Write: /etc/hosts`
  - WebFetch → `WebFetch: https://example.com`
  - Read → `Read: /some/file.py`

## 从老脚本迁移

如果你之前在用 `bark_stop.py` / `bark_notify.py`:

1. 直接 `agentnotify init` 让它把绝对路径形式的三段 hook 合并进 settings.json,会备份原文件。
2. 把硬编码的 device key 搬到 `~/.config/agentnotify/config.toml`(init 时会问)。
3. 老脚本可以删了 — settings.json 改完才会切换调用。

## 排错

**没收到推送**:

1. 先 `agentnotify send "test" "hello"` 单独验通通道。
2. 模拟一段 PermissionRequest payload 验 hook 函数:

   ```bash
   echo '{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}' \
     | agentnotify hook claude-permission
   ```

3. 想看 Claude Code 实际发的 payload:临时把 `command` 改成 `tee /tmp/claude-hook.json | agentnotify hook claude-permission`。

**收到 Stop 推送但没收到权限弹窗推送**:

- 检查 settings.json 里 `PermissionRequest` 这一段是否存在,`agentnotify init --force` 重跑能补齐。
- 旧版 Claude Code(2025 及之前)没有 PermissionRequest 事件,权限请求走 Notification 的 `permission_prompt` 子类型 — 这种情况把 Notification hook 的过滤逻辑放开即可(在 `hooks.py:claude_notification` 里去掉 `"permission" in lowered` 那条 short-circuit)。

## 相关字段(供深度定制参考)

- `Stop` stdin 至少包含 `transcript_path`(JSONL 文件路径);本工具读它的最后一条 assistant 文本。
- `Notification` stdin 包含 `message` 字段,可选 `title` / `matcher` / `notification_type`。
- `PermissionRequest` stdin 包含 `tool_name` + `tool_input`(各工具结构不同),以及 `session_id` / `cwd` / `permission_mode`。
