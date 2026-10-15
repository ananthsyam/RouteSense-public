"""Tests for the admin password gate (src/auth.py) and the app-level gate.

Covers: correct password, incorrect password, missing/empty configuration,
logout, and blocked unauthenticated access.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import auth  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_session(monkeypatch):
    """Give each test an isolated in-memory session and no configured password."""

    state = {}
    monkeypatch.setattr(auth, "_session_state", lambda: state)
    monkeypatch.delenv(auth.ADMIN_PASSWORD_ENV, raising=False)
    yield state


# ---------------------------------------------------------------------------
# Password verification
# ---------------------------------------------------------------------------


def test_correct_password_authenticates(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")

    assert auth.is_configured() is True
    assert auth.verify_password("correct-horse") is True
    assert auth.login("correct-horse") is True
    assert auth.is_authenticated() is True


def test_incorrect_password_is_rejected(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")

    assert auth.verify_password("Correct-Horse") is False
    assert auth.login("wrong-password") is False
    assert auth.login("") is False
    assert auth.is_authenticated() is False


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv(auth.ADMIN_PASSWORD_ENV, raising=False)

    assert auth.get_admin_password() is None
    assert auth.is_configured() is False
    # Nothing may authenticate when the secret is absent.
    assert auth.verify_password("") is False
    assert auth.verify_password("anything") is False
    assert auth.login("anything") is False
    assert auth.is_authenticated() is False


def test_empty_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "    ")

    assert auth.get_admin_password() is None
    assert auth.is_configured() is False
    assert auth.login("    ") is False
    assert auth.is_authenticated() is False


# ---------------------------------------------------------------------------
# Session state handling
# ---------------------------------------------------------------------------


def test_password_is_never_stored_in_session_state(monkeypatch, _fresh_session):
    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")

    assert auth.login("correct-horse") is True
    # Only the boolean flag may exist; never the plaintext password.
    assert dict(_fresh_session) == {auth.SESSION_KEY: True}
    assert "correct-horse" not in repr(_fresh_session)


def test_logout_clears_authenticated_state(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")
    auth.login("correct-horse")
    assert auth.is_authenticated() is True

    auth.logout()
    assert auth.is_authenticated() is False


def test_logout_without_login_is_safe():
    auth.logout()
    assert auth.is_authenticated() is False


# ---------------------------------------------------------------------------
# App-level gate (Database Management page)
# ---------------------------------------------------------------------------


def test_app_gate_blocks_when_secret_missing(monkeypatch):
    import app

    monkeypatch.delenv(auth.ADMIN_PASSWORD_ENV, raising=False)
    assert app._require_admin() is False


def test_app_gate_blocks_unauthenticated_access(monkeypatch):
    import app

    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")
    assert auth.is_authenticated() is False

    # No CRUD controls and no database records are rendered.
    assert app._require_admin() is False
    # The blocked attempt must not authenticate the session.
    assert auth.is_authenticated() is False


def test_app_gate_opens_for_authenticated_session(monkeypatch):
    import app

    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")
    auth.login("correct-horse")
    assert app._require_admin() is True


def test_app_gate_closes_again_after_logout(monkeypatch):
    import app

    monkeypatch.setenv(auth.ADMIN_PASSWORD_ENV, "correct-horse")
    auth.login("correct-horse")
    auth.logout()
    assert app._require_admin() is False


def test_app_route_is_gated_before_crud_renders():
    """Static check: Database Management is behind the admin gate."""

    source = Path(REPO, "app.py").read_text(encoding="utf-8")
    gate = 'if _require_admin():\n            render_database_management()'
    assert gate in source, "Database Management must be gated by _require_admin()"
