"""CRUD SQL correctness and safety tests (``src/crud.py``).

These run **without a database**. They cover:

* the displayed SQL template being identical to the executed statement,
* identifier validation (no raw user input ever reaches the SQL string),
* value parameterisation,
* connection/configuration failures being reported as friendly
  :class:`~src.crud.CrudError` messages rather than leaking raw exceptions.
"""

import sys
from pathlib import Path

import mysql.connector
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src import crud  # noqa: E402


# ---------------------------------------------------------------------------
# Template / executed-statement parity
# ---------------------------------------------------------------------------


def test_fetch_rows_executes_exactly_its_displayed_template(monkeypatch):
    captured = {}

    def fake_run(sql, params=(), **kwargs):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(crud, "_run", fake_run)

    crud.fetch_rows(
        "delivery_attempts",
        limit=25,
        offset=50,
        search="late",
        order_by="attempt_no",
        descending=True,
        filters={"status": "Failed"},
    )

    displayed = crud.select_sql_template(
        "delivery_attempts",
        search=True,
        filters={"status": "Failed"},
        order_by="attempt_no",
        descending=True,
    )
    assert captured["sql"] == displayed
    # search (one LIKE per column) + one filter + LIMIT + OFFSET
    assert len(captured["params"]) == len(crud.TABLE_SPECS["delivery_attempts"]["columns"]) + 3
    assert captured["params"][-2:] == (25, 50)


def test_select_template_never_contains_a_user_value():
    template = crud.select_sql_template("orders", search=True, filters={"status": "Delivered"})
    # Only bound placeholders, never inline literals.
    assert "Delivered" not in template
    assert "%s" in template


# ---------------------------------------------------------------------------
# Identifier validation (injection resistance)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "orders; DROP TABLE orders",
        "orders`",
        "orders'",
        "unknown_table",
        "",
    ],
)
def test_unknown_table_identifiers_are_rejected(table):
    with pytest.raises(crud.CrudError):
        crud.get_spec(table)


def test_unknown_filter_column_is_rejected():
    with pytest.raises(crud.CrudError):
        crud.count_rows("orders", filters={"status) OR 1=1 --": "x"})


def test_unknown_order_column_falls_back_to_primary_key():
    template = crud.select_sql_template("orders", order_by="amount; DROP TABLE orders")
    assert "DROP" not in template
    assert "ORDER BY `order_id` ASC" in template


def test_injection_payload_in_search_is_bound_not_interpolated(monkeypatch):
    captured = {}

    def fake_run(sql, params=(), **kwargs):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(crud, "_run", fake_run)
    payload = "'; DROP TABLE orders; --"

    crud.fetch_rows("orders", search=payload)

    assert payload not in captured["sql"]
    assert any(payload in str(p) for p in captured["params"])


# ---------------------------------------------------------------------------
# Connection / configuration failures become friendly CrudError messages
# ---------------------------------------------------------------------------


def test_missing_configuration_becomes_crud_error(monkeypatch):
    monkeypatch.delenv("ROUTESENSE_MYSQL_PASSWORD", raising=False)
    with pytest.raises(crud.CrudError) as excinfo:
        crud.count_rows("customers")
    assert "ROUTESENSE_MYSQL_PASSWORD" in str(excinfo.value)


def test_connection_error_becomes_crud_error(monkeypatch):
    def boom():
        raise mysql.connector.Error(msg="Can't connect to MySQL server")

    monkeypatch.setattr(crud, "get_mysql_connection", boom)
    with pytest.raises(crud.CrudError):
        crud.fetch_rows("customers")
