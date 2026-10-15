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
"""

from __future__ import annotations

import hmac
import os

try:  # Streamlit is a hard dependency of the app; keep the import soft.
    import streamlit as st
except Exception:  # pragma: no cover - headless / unit use
    st = None

#: Environment / secret key that holds the administrator password.
ADMIN_PASSWORD_ENV = "ROUTESENSE_ADMIN_PASSWORD"

#: ``st.session_state`` key holding only the authenticated flag (never the password).
SESSION_KEY = "routesense_admin_authenticated"

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


def is_authenticated() -> bool:
    """Whether the current session has already authenticated."""

    try:
        return bool(_session_state().get(SESSION_KEY, False))
    except Exception:  # pragma: no cover - defensive
        return False


def login(supplied) -> bool:
    """Authenticate ``supplied`` and, on success, flag the session.

    Returns ``True`` on success. The password itself is discarded immediately.
    """

    if not verify_password(supplied):
        return False
    try:
        _session_state()[SESSION_KEY] = True
    except Exception:  # pragma: no cover - defensive
        return False
    return True


def logout() -> None:
    """Clear the authenticated flag for the current session."""

    try:
        _session_state().pop(SESSION_KEY, None)
    except Exception:  # pragma: no cover - defensive
        pass
