"""Owner-local sessions and scoped, expiring, one-use grants; no frontend secrets."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import re
import secrets
import time
import os
from functools import lru_cache
from pathlib import Path
import subprocess
import csv
import tempfile
import stat

TOKEN_PATTERN = re.compile(r"(?:sk-[\w-]{12,}|gsk_[\w-]{20,}|gh[pousr]_[\w]{20,}|AIza[\w-]{20,}|AQ\.[\w-]{20,}|(?i:bearer)\s+[^\s\"']+)")
QUERY_SECRET = re.compile(r"(?i)([?&](?:ticket|token|access_token|api_key|password)=)[^&\s\"']+")


def redact(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if re.search(r"token|ticket|secret|password|api.?key|audio|transcript", k, re.I) and not (k in {"input_tokens", "output_tokens", "total_tokens"} and (v is None or type(v) is int)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return QUERY_SECRET.sub(r"\1[redacted]", TOKEN_PATTERN.sub("[redacted]", value))
    return value


class TransportLogRedaction(logging.Filter):
    """Uvicorn emits WebSocket URLs on its error logger, even with access_log off."""
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def redact_transport_logs():
    for name in ('uvicorn.error', 'uvicorn.access'):
        logger = logging.getLogger(name)
        if not any(isinstance(item, TransportLogRedaction) for item in logger.filters):
            logger.addFilter(TransportLogRedaction())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@lru_cache(maxsize=1)
def windows_owner_sid():
    command = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/whoami.exe")
    result = subprocess.run([command, "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True, timeout=5)
    sid = next(csv.reader(result.stdout.splitlines()))[1]
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise ValueError("Cannot establish the Windows data owner")
    return sid


def reject_links(path, *, require_file=False):
    """Reject existing redirected ancestors and hardlinked/nonregular leaf files.

    This guards accidental/malicious static paths, not concurrent same-owner OS access.
    """
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            # SQLite creates/deletes rollback journals concurrently. Absence is
            # valid for a prospective path; never combine separate stat snapshots.
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0) == 0xA0000003:
            raise ValueError('Private data path must not contain a link')
        if part == path:
            if stat.S_ISDIR(info.st_mode):
                if require_file:
                    raise ValueError('Private data file is not a regular file')
            # Windows may report a regular file with zero links while its last
            # directory entry is being deleted. It is not a multiply linked file.
            elif not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ValueError('Private data file must be regular and must not be a hardlink')
    return path


def safe_file(path):
    return reject_links(path, require_file=True)


def safe_database(path):
    for suffix in ('', '-journal', '-wal', '-shm'):
        safe_file(str(path) + suffix)


def atomic_private_write(path, content):
    path = Path(path)
    private_directory(path.parent)
    safe_file(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.sight-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        safe_file(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_directory(path):
    """OS permissions protect launch tokens, journals and workspace files on Windows too."""
    path = reject_links(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        descriptor = ctypes.c_void_p()
        convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        convert.restype = wintypes.BOOL
        sddl = "D:P(A;OICI;FA;;;" + windows_owner_sid() + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        if not convert(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
            get_acl = advapi.GetSecurityDescriptorDacl
            get_acl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
            get_acl.restype = wintypes.BOOL
            if not get_acl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
                raise ctypes.WinError(ctypes.get_last_error())
            set_acl = advapi.SetNamedSecurityInfoW
            set_acl.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            set_acl.restype = wintypes.DWORD
            result = set_acl(str(path.resolve()), 1, 0x80000004, None, None, acl, None)
            if result:
                raise ctypes.WinError(result)
        finally:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree.restype = ctypes.c_void_p
            kernel.LocalFree(descriptor)
    else:
        path.chmod(0o700)


@dataclass
class Session:
    id: str
    csrf: str
    expires: float
    owner: str = "owner"


class Sessions:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.sessions = {}
        self.tickets = {}

    def create(self):
        self.sessions = {k: v for k, v in self.sessions.items() if v.expires > self.clock()}
        if len(self.sessions) >= 100:
            raise ValueError("Too many local sessions")
        session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock() + 8 * 3600)
        self.sessions[digest(session.id)] = session
        return session

    def get(self, cookie):
        session = self.sessions.get(digest(cookie or ""))
        return session if session and session.expires > self.clock() else None

    def ticket(self, session):
        self.tickets = {k: v for k, v in self.tickets.items() if v[1] > self.clock()}
        if len(self.tickets) >= 100:
            raise ValueError("Too many outstanding WebSocket tickets")
        token = secrets.token_urlsafe(32)
        self.tickets[digest(token)] = (digest(session.id), self.clock() + 30)
        return token

    def consume(self, token, session):
        grant = self.tickets.pop(digest(token), None)
        return bool(grant and grant[0] == digest(session.id) and grant[1] > self.clock())


class Vault:
    """Use OS credential storage only; never fall back to a plaintext file."""
    ALLOWED = {"groq", "gemini", "openrouter", "chatgpt"}

    def status(self):
        try:
            import keyring
            backend = keyring.get_keyring()
            usable = backend.priority > 0 and not any(x in type(backend).__module__.lower() for x in ("plaintext", "fail", "null"))
            return {"available": usable, "backend": type(backend).__name__, "credentials_checked": False}
        except Exception:
            return {"available": False, "backend": "unavailable", "credentials_checked": False}

    def set(self, provider, value):
        if provider not in self.ALLOWED or not self.status()["available"]:
            raise ValueError("A supported OS credential store is required")
        import keyring
        keyring.set_password("SIGHT", provider, value)

    def get(self, provider):
        if provider not in self.ALLOWED or not self.status()["available"]:
            return None
        import keyring
        try:
            return keyring.get_password("SIGHT", provider)
        except keyring.errors.KeyringError:
            return None
