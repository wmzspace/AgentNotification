from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, config as config_mod, hooks
from ._prompts import ask_text, select_many, select_one
from .installers import (
    InstallStatus,
    install_claude,
    install_codex,
    install_kimi,
)
from .installers._common import backup_file
from .notifiers import Notification, NotifierError, build_notifiers


def _dispatch(cfg, notif: Notification, *, dry_run: bool, quiet: bool) -> int:
    """Send `notif` to every enabled backend. Returns 0 if all succeed.

    In quiet mode (used by hook/wrap) we swallow ALL output — Codex captures
    stderr into its own UI, so a printed traceback or error line shows up to
    the user. The hook's job is to be invisible on failure.
    """
    notifiers, warnings = build_notifiers(cfg)
    if not notifiers:
        if not quiet:
            print(
                f"agentnotify: no backends configured (source: {cfg.source}). "
                f"Run `agentnotify init` or set AGENTNOTIFY_BARK_KEY / AGENTNOTIFY_NTFY_TOPIC.",
                file=sys.stderr,
            )
            for w in warnings:
                print(f"agentnotify: {w}", file=sys.stderr)
        return 0
    rc = 0
    for n in notifiers:
        try:
            status = n.send(notif, dry_run=dry_run)
            if not quiet:
                print(f"[{n.name}] {status}: {notif.title}")
        except NotifierError as e:
            rc = 1
            if not quiet:
                print(f"[{n.name}] error: {e}", file=sys.stderr)
    if not quiet:
        for w in warnings:
            print(f"agentnotify: {w}", file=sys.stderr)
    return rc


# ---------------------------------------------------------------------------
# Subcommands

_AGENT_LABELS = {
    "Claude Code": install_claude,
    "Codex CLI": install_codex,
    "Kimi Code": install_kimi,
}


def _print_ntfy_topic_hint() -> None:
    """Print just enough context for first-time users to pick a usable topic."""
    print("  ↳ topic 是你自定义的字符串,也是访问凭据 (公共 ntfy.sh 谁知道 topic 谁能推)")
    print("  ↳ 选一个不可猜的随机串,如 notify-9f2a1c7e;手机端 ntfy app 订阅同名 topic")
    print()


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else config_mod.default_config_path()
    if path.exists() and not args.force:
        print(f"refusing to overwrite existing {path} (use --force)", file=sys.stderr)
        return 1

    print("AgentNotification setup.\n")

    # 1. Phone OS — drives which backends are even offered.
    try:
        phone = select_one(
            "你的手机系统?",
            choices=["iOS", "Android"],
            default="iOS",
        )
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 1

    bark_key = ""
    bark_server = "https://api.day.app"
    ntfy_topic = ""
    ntfy_server = "https://ntfy.sh"
    backends: list[str] = []

    if phone == "Android":
        # ntfy is the only Android-capable backend.
        print("\nAndroid → 使用 ntfy 推送")
        _print_ntfy_topic_hint()
        ntfy_topic = ask_text("ntfy topic")
        if not ntfy_topic:
            print("no topic provided; aborting", file=sys.stderr)
            return 1
        ntfy_server = ask_text("ntfy server", default="https://ntfy.sh")
        backends.append("ntfy")
    else:
        # iOS heavily restricts background processing, so ntfy.sh's public
        # APNs link only delivers in-app or after 20+ min delay. Bark is
        # the only iOS path that surfaces banners reliably, so don't even
        # offer ntfy here.
        print("\niOS → 使用 Bark 推送")
        from .notifiers.bark import normalize_bark_key
        raw = ask_text("Bark device key 或推送 URL (Bark App 内复制)")
        bark_key = normalize_bark_key(raw)
        if not bark_key:
            print("no Bark device key; aborting", file=sys.stderr)
            return 1
        if raw != bark_key:
            print(f"  (从 URL 提取 key: {bark_key})")
        bark_server = ask_text("Bark server", default="https://api.day.app")
        backends.append("bark")

    # 2. Backup existing agentnotify config if --force overwriting.
    if path.exists() and args.force:
        bk = backup_file(path)
        print(f"\n备份原 config → {bk.name}")

    config_mod.write_initial(
        path,
        backends=backends,
        bark_key=bark_key,
        bark_server=bark_server,
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
    )
    print(f"\nwrote {path}")
    print(f"enabled backends: {', '.join(backends)}")

    # 3. Agent integration — multi-select, then apply.
    try:
        chosen_agents = select_many(
            "\n要自动注入 hook 配置的 agent (Space 多选, Enter 确认, 全部跳过直接 Enter)",
            choices=list(_AGENT_LABELS),
            preselected=[],
        )
    except KeyboardInterrupt:
        chosen_agents = []

    if chosen_agents:
        print()
        for label in chosen_agents:
            installer = _AGENT_LABELS[label]
            try:
                result = installer()
            except Exception as e:  # noqa: BLE001
                print(f"[{label}] failed: {e}", file=sys.stderr)
                continue
            print(result.format())
    else:
        print("\n(跳过 agent 配置注入)")

    print("\nTry it:")
    # Double quotes work in cmd.exe / PowerShell / bash / zsh — single
    # quotes are *not* string delimiters in Windows cmd, so a single-quoted
    # example would print literal apostrophes there.
    print('  agentnotify send "Hello from AgentNotification" "Setup complete"')
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    cfg = config_mod.load()
    notif = Notification(
        title=args.title,
        body=args.body or "",
        url=args.url,
        priority=args.priority,
        group=args.group,
    )
    return _dispatch(cfg, notif, dry_run=args.dry_run, quiet=False)


def cmd_hook(args: argparse.Namespace) -> int:
    # Hooks must NEVER write to stderr or return non-zero — agents surface
    # both to the user (Codex captures stderr into its UI; Claude logs hook
    # failures). We used to rely on a shell tail like `2>/dev/null || true`
    # at the call site, but that's POSIX-only (Windows cmd has no `/dev/null`
    # and no `true`), so we move the suppression into Python itself: catch
    # everything, swallow it, return 0.
    try:
        cfg = config_mod.load()
        notif: Notification | None
        if args.kind == "claude-stop":
            notif = hooks.claude_stop(sys.stdin.read())
        elif args.kind == "claude-notification":
            notif = hooks.claude_notification(sys.stdin.read())
        elif args.kind == "claude-permission":
            notif = hooks.claude_permission(sys.stdin.read())
        elif args.kind == "kimi-stop":
            notif = hooks.kimi_stop(sys.stdin.read())
        elif args.kind == "kimi-notification":
            notif = hooks.kimi_notification(sys.stdin.read())
        elif args.kind == "codex-stop":
            notif = hooks.codex_stop(sys.stdin.read())
        elif args.kind == "codex-permission":
            notif = hooks.codex_permission(sys.stdin.read())
        elif args.kind == "codex":
            notif = hooks.codex(args.payload or "")
        else:
            return 0  # unknown kind — silently no-op, never break the agent

        if notif is not None:
            _dispatch(cfg, notif, dry_run=args.dry_run, quiet=True)
    except Exception:
        pass
    return 0


def cmd_wrap(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    # argparse.REMAINDER keeps a leading `--`; strip it so users can type
    # both `agentnotify wrap -- mycmd args` and `agentnotify wrap mycmd args`.
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("agentnotify wrap: missing command", file=sys.stderr)
        return 2
    cfg = config_mod.load()
    label = args.label or cmd[0]
    start = time.monotonic()
    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError as e:
        print(f"agentnotify wrap: {e}", file=sys.stderr)
        return 127
    elapsed = time.monotonic() - start

    if rc == 0:
        title = f"{label} 完成"
        body = f"用时 {elapsed:.1f}s · exit 0"
    else:
        title = f"{label} 失败"
        body = f"exit {rc} · 用时 {elapsed:.1f}s"

    notif = Notification(title=title, body=body)
    _dispatch(cfg, notif, dry_run=args.dry_run, quiet=True)
    return rc


# ---------------------------------------------------------------------------
# argparse plumbing

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentnotify",
        description="Mobile push notifications for agent CLIs (Claude Code, Codex, Kimi, …).",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="interactively write ~/.config/agentnotify/config.toml")
    pi.add_argument("--path", help="config file path (default: $XDG_CONFIG_HOME/agentnotify/config.toml)")
    pi.add_argument("--force", action="store_true", help="overwrite an existing config file")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("send", help="send a notification manually")
    ps.add_argument("title")
    ps.add_argument("body", nargs="?", default="")
    ps.add_argument("--url", help="tap-through URL")
    ps.add_argument("--priority", type=int, help="ntfy priority 1-5")
    ps.add_argument("--group", help="Bark group")
    ps.add_argument("--dry-run", action="store_true", help="print the request instead of sending")
    ps.set_defaults(func=cmd_send)

    ph = sub.add_parser("hook", help="agent-CLI hook adapters (called by Claude/Codex/etc.)")
    ph.add_argument(
        "kind",
        choices=[
            "claude-stop",
            "claude-notification",
            "claude-permission",
            "kimi-stop",
            "kimi-notification",
            "codex-stop",
            "codex-permission",
            "codex",  # legacy `notify = [...]` JSON-payload form
        ],
    )
    ph.add_argument("payload", nargs="?", help="JSON payload (codex only; otherwise read from stdin)")
    ph.add_argument("--dry-run", action="store_true")
    ph.set_defaults(func=cmd_hook)

    pw = sub.add_parser(
        "wrap",
        help="run any command and push on completion (use this for Kimi or any agent without hooks)",
    )
    pw.add_argument("--label", help="title prefix (defaults to the command name)")
    pw.add_argument("--dry-run", action="store_true")
    pw.add_argument("cmd", nargs=argparse.REMAINDER, help="command and args to run")
    pw.set_defaults(func=cmd_wrap)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
