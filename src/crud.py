"""Backend CRUD operations for the RouteSense MySQL schema.

This module powers the **Data Manager** page of the Streamlit frontend so the
app can Create, Read, Update and Delete rows in the six core tables:

    customers, drivers, vehicles, routes, orders, delivery_attempts

Design notes
------------
* Every table and column identifier is validated against :data:`TABLE_SPECS`,
  so no raw user input ever reaches the SQL string. Values are always passed
  as bound parameters (``%s``).
* :class:`CrudError` wraps low-level MySQL errors into friendly messages that
  are safe to display in the UI.
* The module is dependency-light: it only needs ``mysql-connector-python`` and
  ``pandas`` (both already required by RouteSense) and reuses the connection
  helper from :mod:`src.database`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional, Sequence

import mysql.connector
import pandas as pd

try:  # Normal package import (``from src.crud import ...``).
    from src.database import get_mysql_connection
    from src import sql_inspector
except ImportError:  # pragma: no cover - allows ``python src/crud.py``.
    from database import get_mysql_connection
    import sql_inspector


__all__ = [
    "CrudError",
    "TABLE_SPECS",
    "list_tables",
    "table_specs",
    "get_spec",
    "get_primary_key",
    "count_rows",
    "fetch_rows",
    "fetch_row",
    "fetch_column_values",
    "insert_row",
    "update_row",
    "delete_row",
    "foreign_key_exists",
    "insert_sql_template",
    "update_sql_template",
    "delete_sql_template",
    "select_sql_template",
    "select_by_pk_sql_template",
]


class CrudError(RuntimeError):
    """Raised when a CRUD operation cannot be completed."""


# -----------------------------------------------------------------------------
# Schema specification
# -----------------------------------------------------------------------------
# `type`      : text | int | decimal | date | datetime | enum
# `required`  : NOT NULL columns without a sensible default
# `max`       : display/validation hint for text columns
# `references`: (table, column) for foreign-key dropdowns in the UI
# `options`   : allowed values for enum columns (matches schema.sql)

TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "customers": {
        "label": "Customers",
        "primary_key": "customer_id",
        "columns": {
            "customer_id": {"label": "Customer ID", "type": "text", "required": True, "max": 10},
            "customer_unique_id": {"label": "Customer Unique ID", "type": "text", "required": True, "max": 40},
            "city": {"label": "City", "type": "text", "required": False, "max": 80},
            "zone": {"label": "Zone (state code)", "type": "text", "required": True, "max": 5},
            "region": {"label": "Region", "type": "text", "required": False, "max": 20},
            "pincode": {"label": "Pincode", "type": "text", "required": False, "max": 10},
        },
    },
    "drivers": {
        "label": "Drivers",
        "primary_key": "driver_id",
        "columns": {
            "driver_id": {"label": "Driver ID", "type": "text", "required": True, "max": 10},
            "name": {"label": "Name", "type": "text", "required": True, "max": 100},
            "phone": {"label": "Phone", "type": "text", "required": False, "max": 20},
            "license_no": {"label": "License No", "type": "text", "required": False, "max": 30},
            "experience_years": {"label": "Experience (years)", "type": "int", "required": False, "min": 0},
        },
    },
    "vehicles": {
        "label": "Vehicles",
        "primary_key": "vehicle_id",
        "columns": {
            "vehicle_id": {"label": "Vehicle ID", "type": "text", "required": True, "max": 10},
            "vehicle_type": {"label": "Vehicle Type", "type": "text", "required": True, "max": 30},
            "registration_no": {"label": "Registration No", "type": "text", "required": False, "max": 20},
            "capacity_kg": {"label": "Capacity (kg)", "type": "int", "required": False, "min": 1},
        },
    },
    "routes": {
        "label": "Routes",
        "primary_key": "route_id",
        "columns": {
            "route_id": {"label": "Route ID", "type": "text", "required": True, "max": 10},
            "route_name": {"label": "Route Name", "type": "text", "required": True, "max": 100},
            "zone": {"label": "Zone (state code)", "type": "text", "required": True, "max": 5},
            "origin_hub": {"label": "Origin Hub", "type": "text", "required": False, "max": 100},
            "distance_km": {"label": "Distance (km)", "type": "decimal", "required": False, "min": 0},
            "driver_id": {"label": "Driver", "type": "text", "required": True, "references": ("drivers", "driver_id")},
            "vehicle_id": {"label": "Vehicle", "type": "text", "required": True, "references": ("vehicles", "vehicle_id")},
        },
    },
    "orders": {
        "label": "Orders",
        "primary_key": "order_id",
        "columns": {
            "order_id": {"label": "Order ID", "type": "text", "required": True, "max": 10},
            "olist_order_id": {"label": "Olist Order ID", "type": "text", "required": False, "max": 40},
            "customer_id": {"label": "Customer", "type": "text", "required": True, "references": ("customers", "customer_id")},
            "route_id": {"label": "Route", "type": "text", "required": True, "references": ("routes", "route_id")},
            "order_date": {"label": "Order Date", "type": "date", "required": True},
            "promised_date": {"label": "Promised Date", "type": "date", "required": False},
            "delivery_date": {"label": "Delivery Date", "type": "date", "required": False},
            "status": {
                "label": "Status",
                "type": "enum",
                "required": True,
                "options": ["Delivered", "Failed", "Pending", "In Transit"],
            },
            "amount": {"label": "Amount", "type": "decimal", "required": False, "min": 0},
            "freight_value": {"label": "Freight Value", "type": "decimal", "required": False, "min": 0},
            "zone": {"label": "Zone (state code)", "type": "text", "required": True, "max": 5},
        },
    },
    "delivery_attempts": {
        "label": "Delivery Attempts",
        "primary_key": "attempt_id",
        "columns": {
            "attempt_id": {"label": "Attempt ID", "type": "text", "required": True, "max": 10},
            "order_id": {"label": "Order", "type": "text", "required": True, "references": ("orders", "order_id")},
            "attempt_no": {"label": "Attempt No", "type": "int", "required": True, "min": 1},
            "attempt_time": {"label": "Attempt Time", "type": "datetime", "required": True},
            "status": {"label": "Status", "type": "enum", "required": True, "options": ["Delivered", "Failed"]},
            "failure_reason": {"label": "Failure Reason", "type": "text", "required": False, "max": 100},
            "delay_minutes": {"label": "Delay (minutes)", "type": "int", "required": False, "min": 0},
        },
    },
}


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def get_spec(table: str) -> Dict[str, Any]:
    """Return the specification for ``table`` or raise :class:`CrudError`."""

    if table not in TABLE_SPECS:
        raise CrudError(f"Unknown table '{table}'.")
    return TABLE_SPECS[table]


def list_tables() -> List[str]:
    """Return the managed table names in a stable order."""

    return list(TABLE_SPECS.keys())


def table_specs() -> Dict[str, Dict[str, Any]]:
    """Expose the schema spec (used by the Streamlit UI)."""

    return TABLE_SPECS


def get_primary_key(table: str) -> str:
    return get_spec(table)["primary_key"]


# -----------------------------------------------------------------------------
# SQL template builders
# -----------------------------------------------------------------------------
# These return the exact parameterised statements the CRUD helpers run. They
# are used both internally (so the executed SQL always matches what the UI
# documents) and by the frontend to display the template to the user.


def insert_sql_template(table: str, columns: Sequence[str]) -> str:
    """Template for an INSERT into ``table`` using ``columns``."""

    get_spec(table)
    cols = list(columns)
    placeholders = ", ".join(["%s"] * len(cols))
    return (
        f"INSERT INTO `{table}` ({', '.join(f'`{c}`' for c in cols)}) "
        f"VALUES ({placeholders})"
    )


def update_sql_template(table: str, columns: Sequence[str]) -> str:
    """Template for an UPDATE of ``columns`` in ``table`` (keyed by PK)."""

    spec = get_spec(table)
    pk = spec["primary_key"]
    cols = [c for c in columns if c != pk]
    set_clause = ", ".join(f"`{c}` = %s" for c in cols)
    return f"UPDATE `{table}` SET {set_clause} WHERE `{pk}` = %s"


def delete_sql_template(table: str) -> str:
    """Template for a DELETE of a single row in ``table`` (keyed by PK)."""

    spec = get_spec(table)
    return f"DELETE FROM `{table}` WHERE `{spec['primary_key']}` = %s"


def select_sql_template(
    table: str,
    *,
    search: bool = False,
    filters: Optional[Dict[str, Any]] = None,
    order_by: Optional[str] = None,
    descending: bool = False,
    limit: bool = True,
) -> str:
    """Template for the READ query used by the Data Manager.

    The WHERE/ORDER BY/LIMIT fragments are produced by the same helpers that
    build the *executed* query (see :func:`fetch_rows`), so the template shown
    in the SQL Query Inspector can never drift from what actually runs.
    """

    spec = get_spec(table)
    columns = list(spec["columns"])

    sql = f"SELECT {', '.join(f'`{c}`' for c in columns)} FROM `{table}`"

    # Only the clause text is used here; the bound search value is irrelevant
    # to the template, so a placeholder sentinel is passed for the truthy case.
    where, _params = _build_where(columns, "%s" if search else None, filters)
    sql += where

    order_column = order_by if order_by in spec["columns"] else spec["primary_key"]
    sql += f" ORDER BY `{order_column}` {'DESC' if descending else 'ASC'}"
    if limit:
        sql += " LIMIT %s OFFSET %s"

    return sql


def select_by_pk_sql_template(table: str) -> str:
    """Template for fetching one row of ``table`` by primary key."""

    spec = get_spec(table)
    columns = list(spec["columns"])
    return (
        f"SELECT {', '.join(f'`{c}`' for c in columns)} "
        f"FROM `{table}` WHERE `{spec['primary_key']}` = %s LIMIT 1"
    )


def _friendly_error(exc: mysql.connector.Error) -> str:
    """Convert a raw MySQL error into a human-readable message."""

    errno = exc.errno
    message = (exc.msg or str(exc)).strip()

    if errno == 1062:  # ER_DUP_ENTRY
        return (
            "Duplicate value - a row with this primary/unique key already "
            f"exists. ({message})"
        )
    if errno == 1451:  # Cannot delete/update parent row (child rows exist)
        return (
            "Cannot delete or change this row because other rows reference it "
            f"(foreign-key constraint). ({message})"
        )
    if errno == 1452:  # Cannot add/update child row (parent missing)
        return (
            "A referenced row does not exist. Pick an existing foreign key "
            f"value (for example a valid customer/route/order). ({message})"
        )
    if errno == 1406:  # Data too long
        return f"A value is longer than the column allows. ({message})"
    if errno == 1264:  # Out of range
        return f"A numeric value is out of the allowed range. ({message})"
    if errno == 3819:  # Check constraint violated
        return f"A CHECK constraint was violated. ({message})"

    return f"Database error: {message}"


def _run(
    sql: str,
    params: tuple = (),
    *,
    fetch: bool = False,
    dictionary: bool = False,
    label: Optional[str] = None,
    operation: Optional[str] = None,
):
    """Execute a statement through the shared SQL inspector.

    The statement template, bound parameters, duration, affected/returned row
    count and status are recorded in :mod:`src.sql_inspector`. Writes are
    committed. Returns ``cursor.rowcount`` for writes, or the fetched rows when
    ``fetch=True``.
    """

    try:
        conn = get_mysql_connection()
    except CrudError:
        raise
    except mysql.connector.Error as exc:
        # Connection-level failure (host down, TLS, authentication).
        raise CrudError(_friendly_error(exc)) from exc
    except Exception as exc:  # missing/invalid configuration, bad port, ...
        # The message is safe: it never contains a password or a full URI.
        raise CrudError(str(exc)) from exc

    try:
        result = sql_inspector.execute(
            conn,
            sql,
            params,
            fetch=fetch,
            dictionary=dictionary,
            label=label,
            operation=operation,
        )

        if not fetch:
            conn.commit()

        return result

    except mysql.connector.Error as exc:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - rollback is best-effort
            pass
        raise CrudError(_friendly_error(exc)) from exc

    finally:
        conn.close()


def _coerce(table: str, column: str, value: Any) -> Any:
    """Validate and convert a Python value to the column's expected type."""

    meta = get_spec(table)["columns"][column]

    if value is None or (isinstance(value, str) and value.strip() == ""):
        if meta.get("required"):
            raise CrudError(f"'{meta['label']}' is required.")
        return None

    ctype = meta["type"]

    if ctype == "text":
        text = str(value).strip()
        max_len = meta.get("max")
        if max_len and len(text) > max_len:
            raise CrudError(
                f"'{meta['label']}' is too long (max {max_len} characters)."
            )
        return text

    if ctype == "int":
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise CrudError(f"'{meta['label']}' must be a whole number.") from exc
        if meta.get("min") is not None and number < int(meta["min"]):
            raise CrudError(
                f"'{meta['label']}' must be at least {int(meta['min'])}."
            )
        return number

    if ctype == "decimal":
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise CrudError(f"'{meta['label']}' must be a number.") from exc
        if meta.get("min") is not None and number < float(meta["min"]):
            raise CrudError(
                f"'{meta['label']}' must be at least {float(meta['min'])}."
            )
        return number

    if ctype == "date":
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        try:
            return dt.date.fromisoformat(str(value)[:10])
        except ValueError as exc:
            raise CrudError(
                f"'{meta['label']}' must be a date (YYYY-MM-DD)."
            ) from exc

    if ctype == "datetime":
        if isinstance(value, dt.datetime):
            return value
        if isinstance(value, dt.date):
            return dt.datetime(value.year, value.month, value.day)
        try:
            return dt.datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise CrudError(
                f"'{meta['label']}' must be a date and time."
            ) from exc

    if ctype == "enum":
        text = str(value)
        options = meta.get("options", [])
        if text not in options:
            raise CrudError(
                f"'{meta['label']}' must be one of: {', '.join(options)}."
            )
        return text

    return value


# -----------------------------------------------------------------------------
# Read
# -----------------------------------------------------------------------------


def _validate_filter_columns(spec: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> None:
    for column in filters or {}:
        if column not in spec["columns"]:
            raise CrudError(f"Unknown filter column '{column}'.")


def _build_where(
    columns: List[str],
    search: Optional[str],
    filters: Optional[Dict[str, Any]],
) -> tuple:
    """Build a WHERE fragment + parameters shared by count/read queries."""

    where = []
    params: List[Any] = []

    if search:
        like = f"%{search}%"
        where.append(
            "(" + " OR ".join(f"CAST(`{c}` AS CHAR) LIKE %s" for c in columns) + ")"
        )
        params.extend([like] * len(columns))

    for column, value in (filters or {}).items():
        where.append(f"`{column}` = %s")
        params.append(value)

    clause = " WHERE " + " AND ".join(where) if where else ""
    return clause, params


def _reference_exists(table: str, column: str, value: Any) -> bool:
    sql = f"SELECT `{column}` FROM `{table}` WHERE `{column}` = %s LIMIT 1"
    rows = _run(
        sql,
        (value,),
        fetch=True,
        label=f"Validate reference {table}.{column}",
        operation="SELECT",
    )
    return bool(rows)


def foreign_key_exists(table: str, column: str, value: Any) -> bool:
    """Return True if ``value`` exists as a key in ``table.column``."""

    spec = get_spec(table)
    if column not in spec["columns"]:
        raise CrudError(f"Unknown column '{column}' on table '{table}'.")
    return _reference_exists(table, column, value)


def _validate_references(table: str, payload: Dict[str, Any]) -> None:
    """Reject writes whose foreign-key values do not exist (friendly error)."""

    spec = get_spec(table)
    for name, meta in spec["columns"].items():
        if name in payload and payload[name] is not None and meta.get("references"):
            ref_table, ref_column = meta["references"]
            if not _reference_exists(ref_table, ref_column, payload[name]):
                raise CrudError(
                    f"Referenced {ref_table}.{ref_column} = {payload[name]!r} "
                    "does not exist."
                )


def count_rows(
    table: str,
    search: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> int:
    """Count rows in ``table``, optionally filtered by search/equality."""

    spec = get_spec(table)
    columns = list(spec["columns"])
    _validate_filter_columns(spec, filters)

    where, params = _build_where(columns, search, filters)
    sql = f"SELECT COUNT(*) AS total FROM `{table}`{where}"

    rows = _run(
        sql,
        tuple(params),
        fetch=True,
        dictionary=True,
        label=f"Count rows in {table}",
        operation="SELECT",
    )
    return int(rows[0]["total"]) if rows else 0


def fetch_rows(
    table: str,
    limit: int = 200,
    offset: int = 0,
    search: Optional[str] = None,
    order_by: Optional[str] = None,
    descending: bool = False,
    filters: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Return rows from ``table`` as a DataFrame (search / filters / paging)."""

    spec = get_spec(table)
    columns = list(spec["columns"])
    _validate_filter_columns(spec, filters)

    # Build the executed SQL from the same template that the SQL Query
    # Inspector displays, then add the identical bound parameters.
    sql = select_sql_template(
        table,
        search=bool(search),
        filters=filters,
        order_by=order_by,
        descending=descending,
    )
    _where, params = _build_where(columns, search, filters)
    params.extend([max(int(limit), 1), max(int(offset), 0)])

    rows = _run(
        sql,
        tuple(params),
        fetch=True,
        dictionary=True,
        label=f"Read from {table}",
        operation="SELECT",
    )
    return pd.DataFrame(rows, columns=columns)


def fetch_row(table: str, pk_value: Any) -> Optional[Dict[str, Any]]:
    """Return a single row as a dict, or ``None`` if it does not exist."""

    spec = get_spec(table)
    sql = select_by_pk_sql_template(table)

    rows = _run(
        sql,
        (pk_value,),
        fetch=True,
        dictionary=True,
        label=f"Fetch {table} by {spec['primary_key']}",
        operation="SELECT",
    )
    return rows[0] if rows else None


def fetch_column_values(table: str, column: str, limit: int = 1000) -> List[Any]:
    """Return the non-null values of ``column`` (used to populate dropdowns)."""

    spec = get_spec(table)
    if column not in spec["columns"]:
        raise CrudError(f"Unknown column '{column}' on table '{table}'.")

    sql = (
        f"SELECT `{column}` FROM `{table}` "
        f"WHERE `{column}` IS NOT NULL "
        f"ORDER BY `{column}` LIMIT %s"
    )
    rows = _run(
        sql,
        (max(int(limit), 1),),
        fetch=True,
        label=f"List {table}.{column} values",
        operation="SELECT",
    )
    return [row[0] for row in rows]


# -----------------------------------------------------------------------------
# Write
# -----------------------------------------------------------------------------


def insert_row(table: str, values: Dict[str, Any]) -> None:
    """Insert a new row into ``table``.

    ``values`` maps column names to Python values. Required columns must be
    present and non-empty, foreign keys must reference existing rows, and
    unknown columns raise :class:`CrudError`.
    """

    spec = get_spec(table)
    columns = spec["columns"]

    unknown = set(values) - set(columns)
    if unknown:
        raise CrudError(f"Unknown column(s): {', '.join(sorted(unknown))}.")

    missing = [
        name
        for name, meta in columns.items()
        if meta.get("required") and values.get(name) in (None, "")
    ]
    if missing:
        labels = [columns[name]["label"] for name in missing]
        raise CrudError(f"Missing required field(s): {', '.join(labels)}.")

    if not values:
        raise CrudError("No values provided.")

    payload = {name: _coerce(table, name, value) for name, value in values.items()}
    _validate_references(table, payload)

    keys = list(payload)
    sql = insert_sql_template(table, keys)

    _run(
        sql,
        tuple(payload[k] for k in keys),
        label=f"Create row in {table}",
        operation="INSERT",
    )


def update_row(table: str, pk_value: Any, values: Dict[str, Any]) -> int:
    """Update the row identified by ``pk_value``. Returns affected rows."""

    spec = get_spec(table)
    columns = spec["columns"]
    pk = spec["primary_key"]

    values = {name: value for name, value in values.items() if name != pk}

    unknown = set(values) - set(columns)
    if unknown:
        raise CrudError(f"Unknown column(s): {', '.join(sorted(unknown))}.")

    if not values:
        raise CrudError("No changes provided.")

    for name, value in values.items():
        if columns[name].get("required") and (
            value is None or (isinstance(value, str) and not value.strip())
        ):
            raise CrudError(f"'{columns[name]['label']}' is required.")

    payload = {name: _coerce(table, name, value) for name, value in values.items()}
    _validate_references(table, payload)

    sql = update_sql_template(table, list(payload))
    params = tuple(payload[name] for name in payload) + (pk_value,)

    affected = _run(
        sql,
        params,
        label=f"Update row in {table} where {pk} = {pk_value!r}",
        operation="UPDATE",
    )

    if affected == 0 and fetch_row(table, pk_value) is None:
        raise CrudError("No matching row found to update.")

    return int(affected)


def delete_row(table: str, pk_value: Any) -> int:
    """Delete the row identified by ``pk_value``. Returns affected rows."""

    spec = get_spec(table)
    pk = spec["primary_key"]
    sql = delete_sql_template(table)

    affected = _run(
        sql,
        (pk_value,),
        label=f"Delete row from {table} where {pk} = {pk_value!r}",
        operation="DELETE",
    )

    if affected == 0:
        raise CrudError("No matching row found to delete.")

    return int(affected)
