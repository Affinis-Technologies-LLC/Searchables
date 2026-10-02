"""
The app's password, and the browser sessions signed in with it.

The password is stored only as a salted scrypt hash in <data dir>/auth.json. To reset a forgotten
password, delete that file and restart; the library is untouched. Signing in gives the browser a
random session token; tokens are kept in memory only and expire with the idle time-out, so
restarting the app signs everyone out.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Dict, Optional

from src import config

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def load() -> Optional[dict]:
    """The stored password record, or None when no password has been set yet."""
    try:
        return json.loads(config.AUTH_FILE.read_text())
    except (OSError, ValueError):
        return None


def save(password: str) -> None:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    record = {"algorithm": "scrypt", **_SCRYPT, "salt": salt.hex(), "hash": digest.hex()}
    config.make_private(config.AUTH_FILE.parent)
    tmp = config.AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    try:
        os.chmod(tmp, 0o600)  # Readable by this account only (no effect on Windows, where ACLs apply)
    except OSError:
        pass
    tmp.replace(config.AUTH_FILE)


def verify(password: str) -> bool:
    record = load()
    if not record:
        return False
    params = {k: record[k] for k in ("n", "r", "p", "dklen")}
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(record["salt"]), **params)
    return hmac.compare_digest(candidate, bytes.fromhex(record["hash"]))


def password_problem(password: str, confirm: str) -> Optional[str]:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Use at least {config.MIN_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "The two passwords don't match."
    return None


class Sessions:
    """Signed-in browsers (token → when last active), and the lockout after repeated wrong passwords."""

    def __init__(self) -> None:
        self._tokens: Dict[str, float] = {}
        self._failures = 0
        self._locked_until = 0.0
        self._lock = threading.Lock()

    def start(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = time.time()
        return token

    def active(self, token: Optional[str]) -> bool:
        """Whether a token is signed in and not idle too long; using it counts as activity."""
        now = time.time()
        with self._lock:
            last = self._tokens.get(token or "")
            if last is None:
                return False
            if now - last > config.SESSION_IDLE_MINUTES * 60:
                del self._tokens[token]
                return False
            self._tokens[token] = now
            return True

    def end(self, token: Optional[str]) -> None:
        with self._lock:
            self._tokens.pop(token or "", None)

    def end_others(self, token: str) -> None:
        """After a password change: every other browser is signed out."""
        with self._lock:
            self._tokens = {token: time.time()}

    def locked_for(self) -> int:
        """Seconds until sign-in is allowed again (0 when it is)."""
        return max(0, int(self._locked_until - time.time()) + (self._locked_until > time.time()))

    def failed(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= config.LOGIN_MAX_ATTEMPTS:
                self._failures, self._locked_until = 0, time.time() + config.LOGIN_LOCKOUT_SECONDS

    def succeeded(self) -> None:
        with self._lock:
            self._failures, self._locked_until = 0, 0.0
