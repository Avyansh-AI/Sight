"""Small typed Phase 1 tools. No arbitrary shell or model-directed desktop execution."""
from pathlib import Path
import os
import re
import subprocess

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class FileWrite(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=65536)


class DesktopAction(StrictModel):
    action: str = Field(pattern="^(clipboard.read|app.launch)$")
    application: str = Field(default="", pattern="^(|notepad|calculator)$")


class LocalFiles:
    def __init__(self, root):
        self.root = Path(root)
        if self.is_link(self.root):
            raise ValueError("Workspace must not be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def is_link(path):
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())

    def path(self, name):
        # Flat, user-selected text files only: excludes traversal, ADS, executable types,
        # Windows device names and hidden credential files on either supported OS.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,90}\.(?:txt|md|csv|json)", name):
            raise ValueError("Use a plain .txt, .md, .csv or .json filename in SIGHT's workspace")
        if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
            raise ValueError("Reserved filename")
        target = self.root / name
        if self.is_link(target) or self.is_link(self.root):
            raise ValueError("Symlinks are not permitted")
        return target

    def list(self):
        if self.is_link(self.root):
            raise ValueError("Workspace must not be a link")
        return sorted(p.name for p in self.root.iterdir() if p.is_file() and not self.is_link(p) and p.stat().st_nlink == 1)[:1000]

    def read(self, name):
        target = self.path(name)
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            if os.fstat(f.fileno()).st_nlink != 1:
                raise ValueError("Hard links are not permitted")
            return f.read(65536)

    def write_new(self, name, content):
        target = self.path(name)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "name": name, "bytes": len(content.encode())}


def desktop_invoke(args: DesktopAction, runner=subprocess.run):
    if os.name != "nt":
        raise ValueError("Windows desktop adapter requires the owner's authorized Windows session")
    system_root = Path(os.environ.get("SystemRoot", "C:/Windows"))
    if args.action == "clipboard.read":
        result = runner([str(system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, timeout=5, check=True, shell=False)
        return {"ok": True, "text": result.stdout[:65536], "stored": False}
    executable = {"notepad": "notepad.exe", "calculator": "calc.exe"}.get(args.application)
    if not executable:
        raise ValueError("Select an allowlisted application")
    # A launch is acknowledged only when the executable starts; GUI readiness is separate.
    process = subprocess.Popen([str(system_root / "System32" / executable)], shell=False)
    return {"ok": True, "pid": process.pid, "gui_verified": False}


def registry():
    return [
        {"id": "files.list", "version": "1", "status": "available", "permission_scope": "sight.workspace.read", "risk_tier": "read", "platform": "all", "required_network": [], "secrets": [], "timeout": 5, "rollback": "none", "provenance": "original implementation; Brahma MIT file tools behavioral reference", "tests": ["test_file_workspace_boundaries"]},
        {"id": "files.write", "version": "1", "status": "approval_required", "input_schema": FileWrite.model_json_schema(), "permission_scope": "sight.workspace.create", "risk_tier": "reversible-write", "platform": "all", "required_network": [], "secrets": [], "timeout": 5, "rollback": "owner removes newly created file; no overwrites", "tests": ["test_scoped_approval_replay"]},
        {"id": "desktop", "version": "1", "status": "approval_required" if os.name == "nt" else "hardware-dependent", "input_schema": DesktopAction.model_json_schema(), "permission_scope": "desktop.explicit", "risk_tier": "high", "platform": "windows", "required_network": [], "secrets": [], "timeout": 5, "rollback": "none", "tests": ["test_desktop_requires_authorization"]},
    ]
