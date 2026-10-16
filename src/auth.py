"""Admin authentication for the Database Management (CRUD) page.

The CRUD page is a write capability, so on a public deployment it is gated
behind a single administrator password supplied through the environment
(``ROUTESENSE_ADMIN_PASSWORD``) — typically via Streamlit **secrets**.

Design rules:

* The module **fails closed**: if the password is missing or empty, nobody is
  authorised and the caller must not render any CRUD controls or records.
* The plaintext password is never stored, returned, logged or printed. Only a
  boolean ``authenticated`` flag is kept in ``st.session_state``.
* Comparison uses :func:`hmac.compare_digest` to avoid timing leaks.
* Brute-force attempts are throttled **per browser session**: after
  :data:`MAX_FAILED_ATTEMPTS` consecutive failures the session is locked for
  :data:`LOCKOUT_SECONDS`, and an authenticated session expires after
  :data:`IDLE_TIMEOUT_SECONDS` of inactivity.

Honest limitation: session-scoped throttling is *not* global rate limiting. A
visitor who starts a fresh session gets a fresh allowance, so it slows manual
guessing rather than defending against a distributed attacker. A strong,
random administrator password remains the primary control.
"""

from __future__ import annotations

import hmac
import os
import time

try:  # Streamlit is a hard dependency of the app; keep the import soft.
    import streamlit as st
except Exception:  # pragma: no cover - headless / unit use
    st = None

#: Environment / secret key that holds the administrator password.
ADMIN_PASSWORD_ENV = "ROUTESENSE_ADMIN_PASSWORD"

#: ``st.session_state`` key holding only the authenticated flag (never the password).
SESSION_KEY = "routesense_admin_authenticated"

#: Consecutive failed logins in one browser session before a lockout.
MAX_FAILED_ATTEMPTS = 5

#: Length of the lockout (seconds) once :data:`MAX_FAILED_ATTEMPTS` is reached.
LOCKOUT_SECONDS = 30

#: Log an authenticated session out after this many seconds without activity.
IDLE_TIMEOUT_SECONDS = 30 * 60

_FAILURES_KEY = "routesense_admin_failed_attempts"
_LOCKOUT_KEY = "routesense_admin_lockout_until"
_LAST_SEEN_KEY = "routesense_admin_last_seen"

#: Used only when there is no live Streamlit session (headless / unit tests).
_FALLBACK_STATE: dict = {}


def _session_state():
    """Return the current Streamlit session state, or a headless fallback."""

    if st is None:
        return _FALLBACK_STATE
    try:
        if st.runtime.exists():
            return st.session_state
    except Exception:
        return _FALLBACK_STATE
    return _FALLBACK_STATE


def get_admin_password():
    """Return the configured password, or ``None`` when it is unset/empty.

    The value is read from the environment on every call and is never cached,
    stored or logged by this module.
    """

    value = os.getenv(ADMIN_PASSWORD_ENV)
    if value is None or value.strip() == "":
        return None
    return value


def is_configured() -> bool:
    """True only when a non-empty administrator password is available."""

    return get_admin_password() is not None


def verify_password(supplied) -> bool:
    """Constant-time comparison of ``supplied`` against the configured value.

    Returns ``False`` when the password is not configured or ``supplied`` is
    empty — i.e. it fails closed.
    """

    expected = get_admin_password()
    if expected is None or supplied is None:
        return False
    if str(supplied) == "":
        return False

    try:
        return hmac.compare_digest(
            str(supplied).encode("utf-8"),
            expected.encode("utf-8"),
        )
    except Exception:  # pragma: no cover - defensive
        return False


def lockout_remaining_seconds() -> float:
    """Seconds left in the current session's lockout (``0`` when not locked)."""

    try:
        until = float(_session_state().get(_LOCKOUT_KEY, 0) or 0)
    except Exception:  # pragma: no cover - defensive
        return 0.0
    remaining = until - time.monotonic()
    return remaining if remaining > 0 else 0.0


def is_locked_out() -> bool:
    """Whether the current session is temporarily locked out."""

    return lockout_remaining_seconds() > 0


def _register_failure(state) -> None:
    """Count a failed attempt and start a lockout once the limit is reached."""

    try:
        attempts = int(state.get(_FAILURES_KEY, 0) or 0) + 1
        _session_state()[_FAILURES_KEY] = attempts
        if attempts >= MAX_FAILED_ATTEMPTS:
            _session_state()[_LOCKOUT_KEY] = time.monotonic() + LOCKOUT_SECONDS
    except Exception:  # pragma: no cover - defensive
        pass


def is_authenticated() -> bool:
    """Whether the current session is authenticated and still active.

    Enforces :data:`IDLE_TIMEOUT_SECONDS`: an authenticated session that has
    been idle for too long is revoked and reported as unauthenticated.
    """

    state = _session_state()
    try:
        if not state.get(SESSION_KEY, False):
            return False

        last_seen = float(state.get(_LAST_SEEN_KEY, 0) or 0)
        now = time.monotonic()
        if IDLE_TIMEOUT_SECONDS and last_seen and (now - last_seen) > IDLE_TIMEOUT_SECONDS:
            logout()
            return False

        state[_LAST_SEEN_KEY] = now
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def login(supplied) -> bool:
    """Authenticate ``supplied`` and, on success, flag the session.

    Returns ``True`` on success. The password itself is discarded immediately.
    Failed attempts are counted and lock the session once
    :data:`MAX_FAILED_ATTEMPTS` is reached.
    """

    state = _session_state()

    if lockout_remaining_seconds() > 0:
        return False

    if not verify_password(supplied):
        _register_failure(state)
        return False

    try:
        state[SESSION_KEY] = True
        state[_LAST_SEEN_KEY] = time.monotonic()
        state.pop(_FAILURES_KEY, None)
        state.pop(_LOCKOUT_KEY, None)
    except Exception:  # pragma: no cover - defensive
        return False
    return True


def logout() -> None:
    """Clear the authenticated flag and all privileged session data."""

    state = _session_state()
    for key in (SESSION_KEY, _LAST_SEEN_KEY, _FAILURES_KEY, _LOCKOUT_KEY):
        try:
            state.pop(key, None)
        except Exception:  # pragma: no cover - defensive
            pass
