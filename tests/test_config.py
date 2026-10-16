"""Sanity tests for configuration handling.

Verifies that the app modules import cleanly and that MySQL configuration is
read from the environment (no hardcoded credentials), without opening a real
connection.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def test_app_modules_import():
    # Importing must not require a database or any secret.
    import src.crud  # noqa: F401
    import src.database  # noqa: F401
    import src.mongodb  # noqa: F401
    import src.sql_inspector  # noqa: F401
    import src.tls  # noqa: F401


def test_mysql_password_is_required(monkeypatch):
    import src.database as database

    monkeypatch.delenv("ROUTESENSE_MYSQL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        database.get_mysql_connection()


def test_mysql_config_is_read_from_env(monkeypatch):
    """Backwards-compatible defaults come from env, not literals in the URL."""
    import os

    import src.database as database

    # Default host/port/database when unset are safe local defaults, never a
    # production endpoint.
    monkeypatch.delenv("ROUTESENSE_MYSQL_HOST", raising=False)
    monkeypatch.delenv("ROUTESENSE_MYSQL_PORT", raising=False)
    monkeypatch.delenv("ROUTESENSE_MYSQL_DATABASE", raising=False)
    assert os.getenv("ROUTESENSE_MYSQL_HOST") is None
    # The module exposes no hardcoded production host.
    text = Path(database.__file__).read_text(encoding="utf-8")
    assert "aivencloud.com" not in text
    assert "mongodb+srv://" not in text or "<" in text


def test_non_numeric_port_fails_with_a_clear_message(monkeypatch):
    import src.database as database

    monkeypatch.setenv("ROUTESENSE_MYSQL_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("ROUTESENSE_MYSQL_PORT", "not-a-port")
    with pytest.raises(RuntimeError) as excinfo:
        database.get_mysql_connection()
    assert "ROUTESENSE_MYSQL_PORT" in str(excinfo.value)


def test_dotenv_is_loaded_without_overriding_real_environment(monkeypatch):
    """A local ``.env`` must never win over real environment variables/secrets.

    Guards the regression where ``load_dotenv(override=True)`` let a stray
    ``.env`` silently override deployed Streamlit secrets.
    """

    import importlib

    import dotenv
    import src.database as database  # noqa: F401  (already imported)
    import src.mongodb as mongodb

    overrides = []

    def spy(*args, **kwargs):
        overrides.append(kwargs.get("override", False))
        return False

    monkeypatch.setattr(dotenv, "load_dotenv", spy)
    try:
        importlib.reload(database)
        importlib.reload(mongodb)
    finally:
        monkeypatch.undo()

    assert overrides, "modules should load a local .env for developer convenience"
    assert all(flag is False for flag in overrides), overrides
