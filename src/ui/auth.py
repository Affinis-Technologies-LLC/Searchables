"""
Password sign-in for the app. Single user, on one machine: the password protects the library from
anyone else who can reach the app (other accounts on the machine can open http://127.0.0.1:8501).

The password is stored only as a salted scrypt hash in <data dir>/auth.json. To reset a forgotten
password, delete that file and restart; the library is untouched.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

import streamlit as st

from src import config

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def _load() -> Optional[dict]:
    try:
        return json.loads(config.AUTH_FILE.read_text())
    except (OSError, ValueError):
        return None


def _save(password: str) -> None:
    salt = secrets.token_bytes(16)
    record = {"algorithm": "scrypt", **_SCRYPT, "salt": salt.hex(), "hash": _hash(password, salt).hex()}
    config.AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    try:
        os.chmod(tmp, 0o600)  # Readable by this account only (no effect on Windows, where ACLs apply)
    except OSError:
        pass
    tmp.replace(config.AUTH_FILE)


def _verify(password: str) -> bool:
    record = _load()
    if not record:
        return False
    params = {k: record[k] for k in ("n", "r", "p", "dklen")}
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(record["salt"]), **params)
    return hmac.compare_digest(candidate, bytes.fromhex(record["hash"]))


@st.cache_resource
def _failures() -> dict:
    """Failed attempts, shared by every browser session so reloading the page doesn't reset them."""
    return {"count": 0, "locked_until": 0.0}


def _password_problem(password: str, confirm: str) -> Optional[str]:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        return f"Use at least {config.MIN_PASSWORD_LENGTH} characters."
    if password != confirm:
        return "The two passwords don't match."
    return None


def _sign_in() -> None:
    st.session_state["authenticated"] = True
    st.session_state["last_active"] = time.time()


def sign_out() -> None:
    st.session_state["authenticated"] = False
    st.session_state.pop("last_active", None)


def require_login() -> None:
    """Shows the set-up or sign-in page and stops the script until the user is signed in."""
    now = time.time()
    if st.session_state.get("authenticated"):
        idle = now - st.session_state.get("last_active", now)
        if idle <= config.SESSION_IDLE_MINUTES * 60:
            st.session_state["last_active"] = now
            return
        sign_out()
        st.session_state["auth_message"] = f"Signed out after {config.SESSION_IDLE_MINUTES} minutes of inactivity."

    _, middle, _ = st.columns([1, 1.2, 1])
    with middle:
        st.title("Searchables")
        if _load() is None:
            _setup_form()
        else:
            _sign_in_form(now)
    st.stop()


def _setup_form() -> None:
    st.subheader("Create a password")
    st.caption("The first time you open Searchables, choose a password. You'll need it each time you "
               "open the app. It's stored only as a secure hash on this machine.")
    with st.form("setup"):
        password = st.text_input("Password", type="password", autocomplete="new-password")
        confirm = st.text_input("Confirm password", type="password", autocomplete="new-password")
        if st.form_submit_button("Create password and continue", type="primary"):
            problem = _password_problem(password, confirm)
            if problem:
                st.error(problem)
            else:
                _save(password)
                _sign_in()
                st.rerun()


def _sign_in_form(now: float) -> None:
    st.subheader("Sign in")
    if message := st.session_state.pop("auth_message", None):
        st.info(message)
    failures = _failures()
    locked = failures["locked_until"] - now
    with st.form("sign_in"):
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", disabled=locked > 0)
    if locked > 0:
        st.warning(f"Too many incorrect attempts. Try again in {int(locked) + 1} seconds.")
    elif submitted:
        if _verify(password):
            failures.update(count=0, locked_until=0.0)
            _sign_in()
            st.rerun()
        failures["count"] += 1
        if failures["count"] >= config.LOGIN_MAX_ATTEMPTS:
            failures.update(count=0, locked_until=now + config.LOGIN_LOCKOUT_SECONDS)
            st.rerun()
        st.error("Incorrect password.")
    st.caption(f"Forgotten it? Delete `{config.AUTH_FILE.name}` in the library folder ({config.AUTH_FILE.parent}) "
               "and restart the app to set a new one. Your documents and collections are kept.")


def account_menu() -> None:
    """Sidebar controls: change password and sign out."""
    with st.popover("Account", icon=":material/account_circle:", width="stretch"):
        with st.form("change_password", clear_on_submit=True):
            st.markdown("**Change password**")
            current = st.text_input("Current password", type="password", autocomplete="current-password")
            new = st.text_input("New password", type="password", autocomplete="new-password")
            confirm = st.text_input("Confirm new password", type="password", autocomplete="new-password")
            if st.form_submit_button("Change password"):
                if not _verify(current):
                    st.error("The current password is incorrect.")
                elif problem := _password_problem(new, confirm):
                    st.error(problem)
                else:
                    _save(new)
                    st.success("Password changed.")
        st.button("Sign out", icon=":material/logout:", on_click=sign_out, width="stretch")
