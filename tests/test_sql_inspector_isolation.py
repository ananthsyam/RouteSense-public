"""Tests for SQL-history session isolation and secret redaction.

One visitor must never see another visitor's SQL statements or bound
parameters, and credentials / connection details must never be stored.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import sql_inspector  # noqa: E402

SESSION_KEY = sql_inspector.SESSION_KEY


class _FakeCursor:
    """Minimal cursor double: enough to drive sql_inspector.execute()."""

    def __init__(self, rows=None, fail=None):
        self._rows = rows or []
        self.rowcount = len(self._rows)
        self._fail = fail

    def execute(self, sql, params=None):
        if self._fail is not None:
            raise self._fail

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, dictionary=False):
        return self._cursor


@pytest.fixture(autouse=True)
def _fresh_instrumentation():
    sql_inspector._sink = None
    sql_inspector._buffer.clear()
    yield
    sql_inspector._sink = None
    sql_inspector._buffer.clear()


def _as_session(monkeypatch, state):
    """Pretend a Streamlit runtime is active with the given session state."""

    monkeypatch.setattr(sql_inspector, "_session_state", lambda: state)


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_fresh_visitor_sees_no_other_sessions_history(monkeypatch):
    sql_inspector.install_streamlit_sink()

    session_a = {}
    _as_session(monkeypatch, session_a)
    sql_inspector._emit({"sql": "SELECT secret_a", "operation": "SELECT"})
    assert len(sql_inspector.get_session_history()) == 1

    # A brand-new visitor must see nothing — not A's statement, not the buffer.
    session_b = {}
    _as_session(monkeypatch, session_b)
    assert sql_inspector.get_session_history() == []

    sql_inspector._emit({"sql": "SELECT secret_b", "operation": "SELECT"})
    assert [e["sql"] for e in sql_inspector.get_session_history()] == ["SELECT secret_b"]

    # Switching back to A still shows only A's own history.
    _as_session(monkeypatch, session_a)
    assert [e["sql"] for e in sql_inspector.get_session_history()] == ["SELECT secret_a"]


def test_session_history_is_not_kept_in_the_process_buffer(monkeypatch):
    sql_inspector.install_streamlit_sink()
    state = {}
    _as_session(monkeypatch, state)

    sql_inspector._emit({"sql": "SELECT 1"})

    assert sql_inspector.get_history() == []
    assert len(sql_inspector.get_session_history()) == 1


def test_clear_history_only_clears_the_calling_session(monkeypatch):
    sql_inspector.install_streamlit_sink()

    session_a, session_b = {}, {}

    _as_session(monkeypatch, session_a)
    sql_inspector._emit({"sql": "SELECT a"})

    _as_session(monkeypatch, session_b)
    sql_inspector._emit({"sql": "SELECT b"})

    _as_session(monkeypatch, session_a)
    sql_inspector.clear_history()
    assert sql_inspector.get_session_history() == []

    _as_session(monkeypatch, session_b)
    assert [e["sql"] for e in sql_inspector.get_session_history()] == ["SELECT b"]


def test_headless_uses_the_process_buffer(monkeypatch):
    _as_session(monkeypatch, None)

    sql_inspector._emit({"sql": "SELECT headless"})
    assert [e["sql"] for e in sql_inspector.get_session_history()] == ["SELECT headless"]


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_execute_records_redacted_sql_and_params(monkeypatch):
    sql_inspector.install_streamlit_sink()
    state = {}
    _as_session(monkeypatch, state)

    conn = _FakeConn(_FakeCursor(rows=[{"x": 1}]))
    sql_inspector.execute(
        conn,
        "SELECT * FROM t WHERE uri = 'mongodb+srv://u:pa55@h.mongodb.net/db'",
        ("password=pa55",),
        fetch=True,
        dictionary=True,
    )

    entry = state[SESSION_KEY][-1]
    assert entry["status"] == "success"
    assert entry["operation"] == "SELECT"
    assert entry["rows"] == 1
    assert "pa55" not in entry["sql"]
    assert "mongodb.net" not in entry["sql"]
    assert "pa55" not in entry["params"]


def test_execute_records_redacted_connection_error(monkeypatch):
    sql_inspector.install_streamlit_sink()
    state = {}
    _as_session(monkeypatch, state)

    err = RuntimeError(
        "2003: Can't connect to MySQL server on "
        "'x.h.aivencloud.com:17436' (10060)"
    )
    conn = _FakeConn(_FakeCursor(fail=err))

    with pytest.raises(RuntimeError):
        sql_inspector.execute(conn, "SELECT 1", ())

    entry = state[SESSION_KEY][-1]
    assert entry["status"] == "error"
    assert entry["error"].startswith("RuntimeError:")
    assert "aivencloud.com" not in entry["error"]


def test_real_query_template_is_still_visible(monkeypatch):
    """Redaction must not destroy the readable SQL template."""

    sql_inspector.install_streamlit_sink()
    state = {}
    _as_session(monkeypatch, state)

    conn = _FakeConn(_FakeCursor(rows=[{"x": 1}]))
    sql_inspector.execute(
        conn,
        "SELECT attempt_id FROM delivery_attempts WHERE status = %s",
        ("Failed",),
        fetch=True,
        dictionary=True,
    )

    entry = state[SESSION_KEY][-1]
    assert entry["sql"] == "SELECT attempt_id FROM delivery_attempts WHERE status = %s"
    assert "('Failed',)" == entry["params"]
