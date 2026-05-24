from __future__ import annotations

import enum
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


class InstallStatus(enum.Enum):
    INSTALLED = "installed"      # newly wrote / merged the hook
    ALREADY_PRESENT = "skipped"  # detected an agentnotify entry already
    NO_AGENT = "no-agent"        # agent config dir missing — agent likely not installed


@dataclass
class InstallResult:
    agent: str
    status: InstallStatus
    target: Path
    backup: Path | None = None
    detail: str = ""

    def format(self) -> str:
        if self.status is InstallStatus.INSTALLED:
            extras: list[str] = []
            if self.backup:
                extras.append(f"backup: {self.backup.name}")
            if self.detail:
                extras.append(self.detail)
            suffix = f" ({'; '.join(extras)})" if extras else ""
            return f"[{self.agent}] installed → {self.target}{suffix}"
        if self.status is InstallStatus.ALREADY_PRESENT:
            return f"[{self.agent}] already present in {self.target} — skipped"
        return f"[{self.agent}] {self.detail or 'agent dir missing — skipped'}"


def backup_file(path: Path) -> Path:
    """Copy `path` next to itself with a timestamped suffix; return new path.

    No-op if the file doesn't exist (returns the candidate path anyway so the
    caller can pass it to InstallResult.backup as `None`).
    """
    if not path.exists():
        return path  # caller will not pass this through
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = path.with_name(f"{path.name}.agentnotify-bak-{stamp}")
    shutil.copy2(path, dst)
    return dst
