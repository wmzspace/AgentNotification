"""Interactive prompts for `agentnotify init`.

Thin wrapper around `questionary` so the rest of the CLI doesn't depend on a
specific UI library. Non-TTY callers (CI, piped stdin) fall back to plain
`input()` so init still works headless.
"""
from __future__ import annotations

import sys
from typing import Sequence


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def select_one(message: str, choices: Sequence[str], default: str | None = None) -> str:
    """Single-select via ↑↓+Enter. Returns the chosen string."""
    if _is_tty():
        import questionary
        answer = questionary.select(message, choices=list(choices), default=default).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer
    # Headless fallback: print numbered list, read a number.
    print(message)
    for i, c in enumerate(choices, 1):
        marker = " *" if c == default else ""
        print(f"  {i}. {c}{marker}")
    raw = input(f"choose [1-{len(choices)}]: ").strip()
    if not raw and default is not None:
        return default
    return choices[int(raw) - 1]


def select_many(
    message: str,
    choices: Sequence[str],
    preselected: Sequence[str] = (),
) -> list[str]:
    """Multi-select via ↑↓+Space+Enter. Returns chosen strings (may be empty)."""
    if _is_tty():
        import questionary
        items = [
            questionary.Choice(c, value=c, checked=(c in preselected))
            for c in choices
        ]
        answer = questionary.checkbox(message, choices=items).ask()
        if answer is None:
            raise KeyboardInterrupt
        return list(answer)
    print(message + " (comma-separated indices, empty for none)")
    for i, c in enumerate(choices, 1):
        marker = " *" if c in preselected else ""
        print(f"  {i}. {c}{marker}")
    raw = input("choose: ").strip()
    if not raw:
        return list(preselected)
    out = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok:
            out.append(choices[int(tok) - 1])
    return out


def ask_text(prompt: str, default: str = "") -> str:
    """Single-line free-text input with optional default."""
    if _is_tty():
        import questionary
        answer = questionary.text(prompt, default=default).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer.strip()
    suffix = f" [{default}]" if default else ""
    try:
        v = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        v = ""
    return v or default
