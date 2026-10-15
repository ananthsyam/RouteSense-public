"""SQL instrumentation + bounded query history for the SQL Query Inspector.

Every SQL statement that RouteSense runs should go through
:func:`execute`. That records, for the SQL Query Inspector page:

* the operation type (SELECT / INSERT / UPDATE / DELETE ...),
* the SQL template that was executed,
* the bound parameter values (safely, without secrets),
* success / failure,
* execution duration in milliseconds,
* rows returned or affected,
* a timestamp and a human-readable label.

The history is kept in a process-level bounded buffer **and** mirrored into
Streamlit ``session_state`` (see :func:`install_streamlit_sink`) so the UI can
render it per session without growing without bound.

This module never reads or stores connection strings or passwords. Statement
text, bound parameters and error messages are passed through
:mod:`src.redact` before they are recorded, and the history is scoped to a
single browser session so that one visitor can never read another visitor's
queries or parameters.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

try:  # Streamlit is a hard dependency of the app, but keep this import soft
    import streamlit as st
except Exception:  # pragma: no cover - allows headless/unit use
    st = None

try:  # Normal package import (``from src import sql_inspector``).
    from src import redact
except ImportError:  # pragma: no cover - allows ``python src/sql_inspector.py``.
    import redact


# Maximum number of statements kept in memory / session state.
MAX_HISTORY = 200

# Streamlit session-state key under which the UI reads the history.
SESSION_KEY = "routesense_sql_history"

_lock = threading.Lock()
_buffer: "list[Dict[str, Any]]" = []
_sink: Optional[Callable[[Dict[str, Any]], None]] = None


def _classify(sql: str) -> str:
    """Return the leading SQL keyword (operation) for a statement."""

    stripped = (sql or "").strip()
    if not stripped:
        return "SQL"
    return stripped.split(None, 1)[0].upper()


def _format_params(params: Sequence[Any]) -> str:
    """Render bound parameters as a safe, readable Python tuple.

    Only the *parameters* are shown here - never the connection details.
    """

    try:
        return repr(tuple(params))
    except Exception:  # pragma: no cover - defensive
        return "(<unrenderable parameters>)"


def _format_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _session_state():
    """Return the active Streamlit session state, or ``None`` when headless.

    The SQL history is scoped to a single browser session so that one visitor
    can never read another visitor's statements or bound parameters.
    """

    if st is None:
        return None
    try:
        if st.runtime.exists():
            return st.session_state
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def _emit(entry: Dict[str, Any]) -> None:
    """Record ``entry`` for the current session.

    Under Streamlit the entry goes **only** to the current session's history;
    the process-wide buffer is reserved for headless / unit use (when there is
    no session sink), so no cross-session data is retained while the app runs.
    """

    if _sink is not None:
        try:
            _sink(entry)
            return
        except Exception:
            # Never let instrumentation break the actual database operation.
            pass

    with _lock:
        _buffer.append(entry)
        if len(_buffer) > MAX_HISTORY:
            del _buffer[:-MAX_HISTORY]


def install_streamlit_sink() -> None:
    """Route recorded queries into the *current* session's history (bounded)."""

    if st is None:
        return

    def _session_sink(entry: Dict[str, Any]) -> None:
        state = _session_state()
        if state is None:
            raise RuntimeError("no active Streamlit session")
        history = state.setdefault(SESSION_KEY, [])
        history.append(entry)
        if len(history) > MAX_HISTORY:
            del history[:-MAX_HISTORY]

    global _sink
    _sink = _session_sink


def execute(
    conn,
    sql: str,
    params: Sequence[Any] = (),
    *,
    fetch: bool = False,
    dictionary: bool = False,
    label: Optional[str] = None,
    operation: Optional[str] = None,
):
    """Execute ``sql`` with bound ``params`` and record it.

    Returns the fetched rows when ``fetch`` is true, otherwise the affected
    row count. The caller owns the connection (and any commit/rollback).
    """

    template = (sql or "").strip()
    param_tuple = tuple(params) if params is not None else ()
    op = operation or _classify(template)

    started = time.perf_counter()
    cursor = None
    result = None
    status = "success"
    error: Optional[str] = None
    rows: Optional[int] = None

    try:
        cursor = conn.cursor(dictionary=dictionary)
        cursor.execute(template, param_tuple)
        if fetch:
            result = cursor.fetchall()
            rows = len(result)
        else:
            result = cursor.rowcount
            rows = int(result)
        return result

    except Exception as exc:
        status = "error"
        error = _format_error(exc)
        raise

    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

        _emit(
            {
                "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "operation": op,
                "sql": redact.redact(template),
                "params": redact.redact(_format_params(param_tuple)),
                "param_count": len(param_tuple),
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "rows": rows,
                "label": label or "",
                "error": redact.redact(error) if error else error,
            }
        )


# -----------------------------------------------------------------------------
# History access
# -----------------------------------------------------------------------------


def get_history() -> List[Dict[str, Any]]:
    """Return a copy of the process-level history (oldest first)."""

    with _lock:
        return list(_buffer)


def get_session_history() -> List[Dict[str, Any]]:
    """Return only this session's history.

    When running under Streamlit this never falls back to the process-wide
    buffer, so a fresh visitor cannot see another visitor's statements. The
    process buffer is used only when there is no active session (headless).
    """

    state = _session_state()
    if state is not None:
        try:
            return list(state.setdefault(SESSION_KEY, []))
        except Exception:  # pragma: no cover - defensive
            pass
    return get_history()


def last(label_prefix: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the most recent entry, optionally filtered by label prefix."""

    history = get_session_history()
    for entry in reversed(history):
        if label_prefix is None or str(entry.get("label", "")).startswith(label_prefix):
            return entry
    return None


def clear_history() -> None:
    """Clear the process-level history and the current session history."""

    with _lock:
        _buffer.clear()

    state = _session_state()
    if state is not None:
        try:
            state[SESSION_KEY] = []
        except Exception:
            pass
