"""
Password sign-in for the app. Single user, on one machine: the password protects the library from
anyone else who can reach the app (other accounts on the machine can open http://127.0.0.1:8501).

The password is stored only as a salted scrypt hash in <data dir>/auth.json. To reset a forgotten
password, delete that file and restart; the library is untouched.

Signing in also gives the browser a random session token in a cookie, so reloading the page (a new
Streamlit session) doesn't ask for the password again. Tokens are kept in memory only and expire with
the idle time-out: restarting the app, or closing the browser, signs you out.
"""
import secrets
import time

import streamlit as st

from src import config
from src.auth import load as _load, password_problem as _password_problem, save as _save, verify as _verify

_COOKIE = "searchables_session"


@st.cache_resource
def _failures() -> dict:
    """Failed attempts, shared by every browser session so reloading the page doesn't reset them."""
    return {"count": 0, "locked_until": 0.0}


@st.cache_resource
def _sessions() -> dict:
    """Signed-in browsers: session token → when it was last active."""
    return {}


def _set_cookie(value: str) -> None:
    # A session cookie (no expiry), sent only to this app. An empty value removes it.
    expiry = "" if value else "; max-age=0"
    st.html(f'<script>document.cookie = "{_COOKIE}={value}; path=/; SameSite=Strict{expiry}";</script>',
            unsafe_allow_javascript=True)


def _sign_in() -> None:
    token = secrets.token_urlsafe(32)
    _sessions()[token] = time.time()
    st.session_state["authenticated"] = True
    st.session_state["last_active"] = time.time()
    st.session_state["session_token"] = token
    st.session_state["cookie_change"] = token  # Sent to the browser on the next run (this one is about to end)


def sign_out() -> None:
    _sessions().pop(st.session_state.pop("session_token", None), None)
    st.session_state["authenticated"] = False
    st.session_state.pop("last_active", None)
    st.session_state["cookie_change"] = ""


def require_login() -> None:
    """Shows the set-up or sign-in page and stops the script until the user is signed in."""
    now = time.time()
    limit = config.SESSION_IDLE_MINUTES * 60
    if "authenticated" not in st.session_state:
        # A new Streamlit session (the page was reloaded): the browser's cookie shows it's signed in
        token = st.context.cookies.get(_COOKIE, "")
        last_active = _sessions().get(token)
        if last_active is not None and now - last_active <= limit:
            st.session_state.update(authenticated=True, last_active=last_active, session_token=token)

    cookie = st.session_state.pop("cookie_change", None)
    if cookie is not None:
        _set_cookie(cookie)
    if st.session_state.get("authenticated"):
        idle = now - st.session_state.get("last_active", now)
        if idle <= limit:
            st.session_state["last_active"] = now
            _sessions()[st.session_state["session_token"]] = now
            return
        sign_out()
        _set_cookie(st.session_state.pop("cookie_change"))
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
                    # Other browsers signed in with the old password are signed out
                    token = st.session_state["session_token"]
                    _sessions().clear()
                    _sessions()[token] = time.time()
                    st.success("Password changed.")
        st.button("Sign out", icon=":material/logout:", on_click=sign_out, width="stretch")
