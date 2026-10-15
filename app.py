import os
from datetime import date, datetime, time
from typing import Optional

import pandas as pd
import streamlit as st


# -----------------------------------------------------------------------------
# Streamlit configuration
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="RouteSense",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------------------------------------------------------
# Configuration bridge
# -----------------------------------------------------------------------------
# Streamlit Community Cloud stores secrets in st.secrets. The existing
# RouteSense database modules read environment variables. This bridge lets
# the same codebase work locally, on Railway, and on Streamlit Community Cloud.


def load_streamlit_secrets() -> None:
    """Copy root-level Streamlit secrets into environment variables."""

    secret_keys = [
        "ROUTESENSE_MYSQL_HOST",
        "ROUTESENSE_MYSQL_PORT",
        "ROUTESENSE_MYSQL_USER",
        "ROUTESENSE_MYSQL_PASSWORD",
        "ROUTESENSE_MYSQL_DATABASE",
        "ROUTESENSE_MYSQL_SSL_CA",
        "ROUTESENSE_ATLAS_URI",
        "ROUTESENSE_ATLAS_USER",
        "ROUTESENSE_ATLAS_PASSWORD",
        "ROUTESENSE_MONGODB_DATABASE",
        "ROUTESENSE_MONGODB_COLLECTION",
    ]

    try:
        for key in secret_keys:
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        # Local .env / Railway environment variables can still work even when
        # Streamlit secrets are not configured.
        pass


load_streamlit_secrets()


# Import after the configuration bridge so both database modules see the
# correct environment values when their functions are called.
from src.database import load_integrated_data  # noqa: E402
from src.mongodb import (  # noqa: E402
    get_collection,
    get_kpis,
    get_failure_summary,
    get_hourly_summary,
    get_route_hotspots,
)
from src import crud  # noqa: E402
from src import sql_inspector  # noqa: E402
from src import auth  # noqa: E402
from src import redact  # noqa: E402


# Capture every SQL statement the app runs into the SQL Query Inspector.
sql_inspector.install_streamlit_sink()


# -----------------------------------------------------------------------------
# Cached data loaders
# -----------------------------------------------------------------------------


@st.cache_data(ttl=600, show_spinner=False)
def load_sql_data() -> pd.DataFrame:
    """Load the integrated SQL dataset."""
    return load_integrated_data()


@st.cache_resource(show_spinner=False)
def load_mongo_collection():
    """Open the MongoDB Atlas collection."""
    return get_collection()


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------


def format_number(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def safe_round(df: pd.DataFrame, columns: list[str], digits: int = 2) -> pd.DataFrame:
    result = df.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(
                result[column], errors="coerce"
            ).fillna(0).round(digits)
    return result


def calculate_sql_kpis(df: pd.DataFrame) -> dict:
    """Fallback KPI calculations using the SQL integrated data."""

    total_attempts = len(df)
    failed_attempts = int(
        (df["attempt_status"] == "Failed").sum()
    ) if "attempt_status" in df.columns else 0
    delivered_attempts = int(
        (df["attempt_status"] == "Delivered").sum()
    ) if "attempt_status" in df.columns else 0

    unique_events = (
        int(df["attempt_id"].nunique())
        if "attempt_id" in df.columns
        else total_attempts
    )

    failure_rate = (
        failed_attempts / total_attempts * 100
        if total_attempts
        else 0.0
    )

    return {
        "total_attempts": total_attempts,
        "failed_attempts": failed_attempts,
        "delivered_attempts": delivered_attempts,
        "unique_events": unique_events,
        "failure_rate": failure_rate,
    }


def calculate_sql_failure_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback failure analytics using SQL data."""

    required = {
        "attempt_status",
        "failure_reason",
        "delay_minutes",
    }

    if not required.issubset(df.columns):
        return pd.DataFrame(
            columns=[
                "failure_reason",
                "failures",
                "average_delay",
                "maximum_delay",
            ]
        )

    failed = df[df["attempt_status"] == "Failed"].copy()

    if failed.empty:
        return pd.DataFrame(
            columns=[
                "failure_reason",
                "failures",
                "average_delay",
                "maximum_delay",
            ]
        )

    failed["failure_reason"] = (
        failed["failure_reason"]
        .fillna("Unknown")
        .astype(str)
    )

    failed["delay_minutes"] = pd.to_numeric(
        failed["delay_minutes"],
        errors="coerce",
    ).fillna(0)

    result = (
        failed.groupby("failure_reason", as_index=False)
        .agg(
            failures=("failure_reason", "size"),
            average_delay=("delay_minutes", "mean"),
            maximum_delay=("delay_minutes", "max"),
        )
        .sort_values("failures", ascending=False)
    )

    return result


def calculate_sql_hourly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback hourly attempt/failure analysis using SQL data."""

    required = {"attempt_time", "attempt_status"}
    if not required.issubset(df.columns):
        return pd.DataFrame(
            columns=[
                "_id",
                "total_attempts",
                "failed_attempts",
                "failure_rate",
            ]
        )

    data = df.copy()
    data["attempt_time"] = pd.to_datetime(
        data["attempt_time"], errors="coerce"
    )
    data = data.dropna(subset=["attempt_time"])

    if data.empty:
        return pd.DataFrame(
            columns=[
                "_id",
                "total_attempts",
                "failed_attempts",
                "failure_rate",
            ]
        )

    data["hour"] = data["attempt_time"].dt.hour
    data["failed"] = (data["attempt_status"] == "Failed").astype(int)

    result = (
        data.groupby("hour", as_index=False)
        .agg(
            total_attempts=("attempt_status", "size"),
            failed_attempts=("failed", "sum"),
        )
        .rename(columns={"hour": "_id"})
    )

    result["failure_rate"] = (
        result["failed_attempts"]
        / result["total_attempts"]
        * 100
    ).fillna(0)

    return result.sort_values("_id")


def calculate_sql_route_hotspots(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback route hotspot analysis using SQL data."""

    required = {
        "route_id",
        "order_id",
        "attempt_status",
    }

    if not required.issubset(df.columns):
        return pd.DataFrame(
            columns=[
                "_id",
                "total_orders",
                "failed_orders",
                "repeat_failure_orders",
                "failure_rate",
                "repeat_failure_rate",
                "hotspot_score",
            ]
        )

    data = df[
        ["route_id", "order_id", "attempt_status"]
    ].dropna(subset=["route_id", "order_id"]).copy()

    if data.empty:
        return pd.DataFrame(
            columns=[
                "_id",
                "total_orders",
                "failed_orders",
                "repeat_failure_orders",
                "failure_rate",
                "repeat_failure_rate",
                "hotspot_score",
            ]
        )

    # One row per route + order.
    order_level = (
        data.groupby(["route_id", "order_id"], as_index=False)
        .agg(
            failed_attempts=(
                "attempt_status",
                lambda s: int((s == "Failed").sum()),
            )
        )
    )

    order_level["failed"] = (
        order_level["failed_attempts"] > 0
    ).astype(int)

    route_level = (
        order_level.groupby("route_id", as_index=False)
        .agg(
            total_orders=("order_id", "size"),
            failed_orders=("failed", "sum"),
            repeat_failure_orders=(
                "failed_attempts",
                lambda s: int((s > 1).sum()),
            ),
        )
        .rename(columns={"route_id": "_id"})
    )

    route_level = route_level[
        route_level["total_orders"] >= 100
    ].copy()

    if route_level.empty:
        route_level["failure_rate"] = pd.Series(dtype=float)
        route_level["repeat_failure_rate"] = pd.Series(dtype=float)
        route_level["hotspot_score"] = pd.Series(dtype=float)
        return route_level

    route_level["failure_rate"] = (
        route_level["failed_orders"]
        / route_level["total_orders"]
        * 100
    )

    route_level["repeat_failure_rate"] = (
        route_level["repeat_failure_orders"]
        / route_level["total_orders"]
        * 100
    )

    max_failure = route_level["failure_rate"].max()
    max_repeat = route_level["repeat_failure_rate"].max()
    max_volume = route_level["total_orders"].max()

    route_level["hotspot_score"] = 0.0

    if max_failure > 0:
        route_level["hotspot_score"] += (
            route_level["failure_rate"]
            / max_failure
            * 60
        )

    if max_repeat > 0:
        route_level["hotspot_score"] += (
            route_level["repeat_failure_rate"]
            / max_repeat
            * 30
        )

    if max_volume > 0:
        route_level["hotspot_score"] += (
            route_level["total_orders"]
            / max_volume
            * 10
        )

    return route_level.sort_values(
        "hotspot_score", ascending=False
    )


def route_explorer_failure_rates(route_data: pd.DataFrame) -> tuple[int, int, float]:
    total_orders = (
        route_data["order_id"].nunique()
        if "order_id" in route_data.columns
        else 0
    )

    failed_orders = (
        route_data.loc[
            route_data["attempt_status"] == "Failed",
            "order_id",
        ].nunique()
        if {"attempt_status", "order_id"}.issubset(route_data.columns)
        else 0
    )

    failure_rate = (
        failed_orders / total_orders * 100
        if total_orders
        else 0.0
    )

    return total_orders, failed_orders, failure_rate


# -----------------------------------------------------------------------------
# MongoDB analytics wrappers
# -----------------------------------------------------------------------------


def mongo_failure_summary(collection) -> pd.DataFrame:
    result = get_failure_summary(collection)
    return pd.DataFrame(result)


def mongo_hourly_summary(collection) -> pd.DataFrame:
    result = get_hourly_summary(collection)
    return pd.DataFrame(result)


def mongo_route_hotspots(collection) -> pd.DataFrame:
    result = get_route_hotspots(collection)
    return pd.DataFrame(result)


# -----------------------------------------------------------------------------
# Database Management (full CRUD over the live MySQL database)
# -----------------------------------------------------------------------------

# These helpers render Create / Read / Update / Delete controls for the six
# core tables (delivery_attempts is the primary CRUD entity). Every action
# talks directly to MySQL through src.crud, so the screen always reflects the
# live database. Every statement is also captured by src.sql_inspector and can
# be reviewed on the "SQL Query Inspector" page. After a successful write the
# data caches are cleared and the page reruns, giving immediate live updates.


# delivery_attempts is the primary CRUD entity, so it leads the selector.
_ENTITY_ORDER = [
    "delivery_attempts",
    "orders",
    "customers",
    "routes",
    "drivers",
    "vehicles",
]


def _table_selector(key: str) -> str:
    """Render an entity picker (delivery_attempts first) with friendly labels."""

    available = crud.list_tables()
    tables = [name for name in _ENTITY_ORDER if name in available]
    tables += [name for name in available if name not in tables]
    labels = {name: crud.TABLE_SPECS[name]["label"] for name in tables}

    return st.selectbox(
        "Entity",
        tables,
        format_func=lambda name: f"{labels[name]} ({name})",
        key=key,
    )


def _flash(message: str, level: str = "success") -> None:
    """Queue a message to show after the next rerun."""

    st.session_state.setdefault("dm_flash", []).append((level, message))


def _show_flash() -> None:
    """Display and clear queued messages."""

    for level, message in st.session_state.pop("dm_flash", []):
        getattr(st, level)(message)


def _refresh_after_write() -> None:
    """Invalidate cached analytics so the dashboard reflects the live data."""

    st.cache_data.clear()


def _column_label(meta: dict, column: str) -> str:
    """Human label for a column, flagging required fields with ``*``."""

    label = meta.get("label", column)
    if meta.get("required"):
        label += " *"
    return label


def _render_query_card(entry: dict, heading: str = "") -> None:
    """Render one inspected SQL statement (template, params, outcome)."""

    if not entry:
        return

    if heading:
        st.markdown(f"**{heading}**")

    success = entry.get("status") == "success"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Operation", entry.get("operation", "-"))
    c2.metric("Status", ("✅ " if success else "❌ ") + str(entry.get("status", "-")))
    duration = entry.get("duration_ms")
    c3.metric("Duration", f"{duration} ms" if duration is not None else "-")
    rows = entry.get("rows")
    c4.metric("Rows affected/returned", rows if rows is not None else "-")

    detail = " · ".join(
        part
        for part in (entry.get("label", ""), entry.get("timestamp", ""))
        if part
    )
    if detail:
        st.caption(detail)

    st.code(entry.get("sql", ""), language="sql")
    st.caption("Parameters (bound separately with %s — never concatenated into the SQL):")
    st.code(entry.get("params", "()"), language="python")

    if entry.get("error"):
        st.error(entry["error"])


def _show_failed_sql() -> None:
    """If the most recent statement failed, show its SQL for transparency."""

    entry = sql_inspector.last()
    if entry and entry.get("status") == "error":
        _render_query_card(entry, "SQL attempted (failed)")


def _remember_write(context: str) -> None:
    """Stash the just-executed write so it can be shown after the rerun."""

    st.session_state["dm_last_write"] = (sql_inspector.last(), context)


def _show_recent_write() -> None:
    """Display the most recent CREATE/UPDATE/DELETE and its SQL."""

    entry, context = st.session_state.get("dm_last_write", (None, None))
    if entry:
        st.success(context or "Operation completed.")
        _render_query_card(entry, "SQL executed")


def render_crud_field(
    table: str,
    column: str,
    meta: dict,
    default=None,
    key_prefix: str = "",
):
    """Render one input widget for a column and return its value."""

    label = _column_label(meta, column)
    required = meta.get("required", False)
    ctype = meta["type"]
    key = f"{key_prefix}_{column}"

    # ---------------------------------------------------------------- FK
    reference = meta.get("references")
    if reference:
        ref_table, ref_column = reference

        try:
            ref_total = crud.count_rows(ref_table)
            options = crud.fetch_column_values(ref_table, ref_column) if ref_total <= 1000 else []
        except crud.CrudError:
            ref_total, options = 0, []

        if options:
            if not required:
                options = [""] + options
            index = options.index(default) if default in options else 0
            choice = st.selectbox(label, options, index=index, key=key)
            return choice or None

        # Too many reference rows — allow free text entry instead.
        st.caption(f"↳ references `{ref_table}.{ref_column}` ({ref_total:,} rows)")
        value = st.text_input(
            label,
            value="" if default is None else str(default),
            key=key,
        )
        return value.strip() or None

    # -------------------------------------------------------------- enum
    if ctype == "enum":
        options = meta["options"]
        index = options.index(default) if default in options else 0
        return st.selectbox(label, options, index=index, key=key)

    # -------------------------------------------------------------- text
    if ctype == "text":
        value = st.text_input(
            label,
            value="" if default is None else str(default),
            key=key,
        )
        return value.strip() or None

    # --------------------------------------------------------------- int
    if ctype == "int":
        minimum = meta.get("min")
        seed = int(default) if default is not None else int(minimum or 0)

        if not required:
            enabled = st.checkbox(
                f"Set {label}", value=default is not None, key=key + "_enabled"
            )
            if not enabled:
                return None

        kwargs = {"min_value": int(minimum)} if minimum is not None else {}
        return int(st.number_input(label, value=seed, step=1, key=key, **kwargs))

    # ----------------------------------------------------------- decimal
    if ctype == "decimal":
        minimum = meta.get("min")
        seed = float(default) if default is not None else float(minimum or 0)

        if not required:
            enabled = st.checkbox(
                f"Set {label}", value=default is not None, key=key + "_enabled"
            )
            if not enabled:
                return None

        kwargs = {"min_value": float(minimum)} if minimum is not None else {}
        return float(
            st.number_input(
                label, value=seed, step=0.01, format="%.2f", key=key, **kwargs
            )
        )

    # -------------------------------------------------------------- date
    if ctype == "date":
        seed = (
            default
            if isinstance(default, date) and not isinstance(default, datetime)
            else date.today()
        )

        if not required:
            enabled = st.checkbox(
                f"Set {label}", value=default is not None, key=key + "_enabled"
            )
            if not enabled:
                return None

        return st.date_input(label, value=seed, key=key)

    # ---------------------------------------------------------- datetime
    if ctype == "datetime":
        if isinstance(default, datetime):
            seed_date = default.date()
            seed_time = default.time().replace(microsecond=0)
        else:
            seed_date, seed_time = date.today(), time(0, 0)

        if not required:
            enabled = st.checkbox(
                f"Set {label}", value=default is not None, key=key + "_enabled"
            )
            if not enabled:
                return None

        chosen_date = st.date_input(label, value=seed_date, key=key + "_date")
        chosen_time = st.time_input("Time", value=seed_time, key=key + "_time")
        return datetime.combine(chosen_date, chosen_time)

    return None


def render_crud_fields(
    table: str,
    defaults: Optional[dict] = None,
    key_prefix: str = "",
    readonly: tuple = (),
) -> dict:
    """Lay out all columns of a table in two columns and collect values."""

    spec = crud.TABLE_SPECS[table]
    defaults = defaults or {}
    left, right = st.columns(2)
    values: dict = {}

    for index, (column, meta) in enumerate(spec["columns"].items()):
        target = left if index % 2 == 0 else right
        with target:
            if column in readonly:
                current = defaults.get(column)
                st.text_input(
                    _column_label(meta, column),
                    value="" if current is None else str(current),
                    disabled=True,
                    key=f"{key_prefix}_{column}_readonly",
                )
                continue

            values[column] = render_crud_field(
                table,
                column,
                meta,
                default=defaults.get(column),
                key_prefix=key_prefix,
            )

    return values


def _pick_primary_key(table: str, key_prefix: str):
    """Let the user choose a row.

    Small tables get a dropdown; large tables get an optional Order ID lookup
    (when the table has an ``order_id`` column) plus a direct key search.
    """

    spec = crud.TABLE_SPECS[table]
    columns = spec["columns"]
    pk = spec["primary_key"]

    try:
        total = crud.count_rows(table)
    except crud.CrudError as exc:
        st.error(redact.redact(str(exc)))
        return None

    if total == 0:
        st.info(f"`{table}` has no rows yet.")
        return None

    if total <= 1000:
        try:
            options = crud.fetch_column_values(table, pk, limit=1000)
        except crud.CrudError as exc:
            st.error(redact.redact(str(exc)))
            return None

        if not options:
            st.info(f"`{table}` has no rows yet.")
            return None

        return st.selectbox(
            _column_label(columns[pk], pk),
            options,
            key=f"{key_prefix}_pk_{table}",
        )

    # Large table: offer an Order ID lookup to make records easy to find.
    if "order_id" in columns and pk != "order_id":
        lookup = st.text_input(
            "Find by Order ID (optional)", key=f"{key_prefix}_order_{table}"
        ).strip()
        if lookup:
            try:
                matches = crud.fetch_rows(
                    table, limit=500, filters={"order_id": lookup}, order_by=pk
                )
            except crud.CrudError as exc:
                st.error(redact.redact(str(exc)))
                matches = pd.DataFrame()

            if matches.empty:
                st.warning(f"No rows in `{table}` for order_id = {lookup!r}.")
            else:
                return st.selectbox(
                    _column_label(columns[pk], pk),
                    matches[pk].tolist(),
                    key=f"{key_prefix}_match_{table}",
                )

    st.caption(f"`{table}` has {total:,} rows — type the `{pk}` directly.")
    entered = st.text_input(
        _column_label(columns[pk], pk), key=f"{key_prefix}_pk_text_{table}"
    ).strip()
    return entered or None


def _render_show_tab() -> None:
    table = _table_selector("dm_show_table")
    spec = crud.TABLE_SPECS[table]
    columns = list(spec["columns"])
    pk = spec["primary_key"]

    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        search = st.text_input(
            "Search (Attempt ID / Order ID / any value)", key="dm_show_search"
        )
    with c2:
        order_by = st.selectbox(
            "Sort by",
            columns,
            index=columns.index(pk),
            key="dm_show_order",
        )
    with c3:
        descending = st.checkbox("Newest first", value=True, key="dm_show_desc")

    filters: dict = {}
    if "status" in columns:
        status_options = ["All"] + list(spec["columns"]["status"].get("options", []))
        chosen_status = st.selectbox(
            "Filter by status", status_options, key="dm_show_status"
        )
        if chosen_status != "All":
            filters["status"] = chosen_status

    limit = st.slider("Rows to display", 10, 1000, 100, 10, key="dm_show_limit")

    st.caption("SELECT query used (values are bound as %s parameters):")
    st.code(
        crud.select_sql_template(
            table,
            search=bool(search),
            filters=filters or None,
            order_by=order_by,
            descending=descending,
        ),
        language="sql",
    )

    try:
        total = crud.count_rows(table, search or None, filters or None)
        df = crud.fetch_rows(
            table,
            limit=limit,
            search=search or None,
            order_by=order_by,
            descending=descending,
            filters=filters or None,
        )
    except crud.CrudError as exc:
        st.error(redact.redact(str(exc)))
        return

    st.caption(f"{total:,} matching row(s) — showing {len(df):,} live from MySQL.")

    if df.empty:
        st.info("No rows to display.")
        return

    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        f"{table}.csv",
        "text/csv",
        key="dm_show_download",
    )

    st.divider()
    st.subheader("Inspect a record")
    st.caption("Select a record from the results above to view its full details.")

    selected = st.selectbox(
        _column_label(spec["columns"][pk], pk),
        df[pk].tolist(),
        key="dm_show_inspect",
    )

    if selected is None:
        return

    try:
        row = crud.fetch_row(table, selected)
    except crud.CrudError as exc:
        st.error(redact.redact(str(exc)))
        return

    if row is None:
        st.warning(f"No row found with `{pk}` = {selected!r}.")
        return

    st.code(crud.select_by_pk_sql_template(table), language="sql")
    st.caption(f"Parameter: ({selected!r},)")
    st.dataframe(pd.DataFrame([row]), use_container_width=True, hide_index=True)


def _render_add_tab() -> None:
    table = _table_selector("dm_add_table")
    spec = crud.TABLE_SPECS[table]
    st.caption(
        "Fields marked with * are required by the database schema. "
        "Foreign keys are validated before the write."
    )

    st.caption("INSERT template used (parameters are bound separately):")
    st.code(crud.insert_sql_template(table, list(spec["columns"])), language="sql")

    with st.form(f"dm_add_form_{table}", clear_on_submit=True):
        values = render_crud_fields(table, key_prefix=f"dm_add_{table}")
        submitted = st.form_submit_button("➕ Add row", type="primary")

    if submitted:
        payload = {name: value for name, value in values.items() if value is not None}
        try:
            crud.insert_row(table, payload)
        except crud.CrudError as exc:
            st.error(redact.redact(str(exc)))
            _show_failed_sql()
        else:
            _refresh_after_write()
            _remember_write(f"New row created in `{table}`.")
            st.rerun()


def _render_update_tab() -> None:
    table = _table_selector("dm_update_table")
    spec = crud.TABLE_SPECS[table]
    pk = spec["primary_key"]

    pk_value = _pick_primary_key(table, "dm_update")
    if pk_value is None:
        return

    try:
        row = crud.fetch_row(table, pk_value)
    except crud.CrudError as exc:
        st.error(redact.redact(str(exc)))
        return

    if row is None:
        st.warning(f"No row found with `{pk}` = {pk_value!r}.")
        return

    st.caption(f"Editing live row where `{pk}` = {pk_value}.")
    st.caption("UPDATE template used (parameters are bound separately):")
    st.code(crud.update_sql_template(table, list(spec["columns"])), language="sql")

    key_prefix = f"dm_upd_{table}_{pk_value}"

    with st.form(f"dm_update_form_{key_prefix}"):
        values = render_crud_fields(
            table, defaults=row, key_prefix=key_prefix, readonly=(pk,)
        )
        submitted = st.form_submit_button("💾 Save changes", type="primary")

    if submitted:
        try:
            crud.update_row(table, pk_value, values)
        except crud.CrudError as exc:
            st.error(redact.redact(str(exc)))
            _show_failed_sql()
        else:
            _refresh_after_write()
            _remember_write(f"Updated `{pk}` = {pk_value} in `{table}`.")
            st.rerun()


def _render_delete_tab() -> None:
    table = _table_selector("dm_delete_table")
    spec = crud.TABLE_SPECS[table]
    pk = spec["primary_key"]

    pk_value = _pick_primary_key(table, "dm_delete")
    if pk_value is None:
        return

    try:
        row = crud.fetch_row(table, pk_value)
    except crud.CrudError as exc:
        st.error(redact.redact(str(exc)))
        return

    if row is None:
        st.warning(f"No row found with `{pk}` = {pk_value!r}.")
        return

    st.caption("DELETE template used (parameters are bound separately):")
    st.code(crud.delete_sql_template(table), language="sql")
    st.write("The following live row will be deleted:")
    st.dataframe(pd.DataFrame([row]), use_container_width=True, hide_index=True)

    confirm = st.checkbox(
        "Yes, permanently delete this row",
        key=f"dm_delete_confirm_{table}_{pk_value}",
    )

    if st.button(
        "🗑️ Delete row",
        type="primary",
        disabled=not confirm,
        key=f"dm_delete_btn_{table}_{pk_value}",
    ):
        try:
            crud.delete_row(table, pk_value)
        except crud.CrudError as exc:
            st.error(redact.redact(str(exc)))
            _show_failed_sql()
        else:
            _refresh_after_write()
            _remember_write(f"Deleted `{pk}` = {pk_value} from `{table}`.")
            st.rerun()


def _require_admin() -> bool:
    """Gate the CRUD page behind the administrator password.

    Fails closed: if ``ROUTESENSE_ADMIN_PASSWORD`` is missing or empty, no CRUD
    controls and no database records are rendered. When authenticated, only a
    boolean flag is held in ``st.session_state`` — the password itself is never
    stored.
    """

    if not auth.is_configured():
        st.header("Database Management")
        st.error(
            "🔒 Administrator access is **not configured**. Set "
            "`ROUTESENSE_ADMIN_PASSWORD` in this app's secrets to enable "
            "database management. No database records are shown until then."
        )
        return False

    if auth.is_authenticated():
        _, right = st.columns([3, 1])
        with right:
            if st.button("🔓 Log out", use_container_width=True):
                auth.logout()
                st.session_state.pop("dm_last_write", None)
                st.session_state.pop("dm_flash", None)
                st.rerun()
        return True

    st.header("Database Management")
    st.info("🔒 Administrator access required for database management.")

    with st.form("routesense_admin_login", clear_on_submit=True):
        supplied = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        if auth.login(supplied):
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


def render_database_management() -> None:
    """Full CRUD screen: Read / Create / Update / Delete against live MySQL."""

    st.header("Database Management")
    st.caption(
        "Create, read, update and delete rows in the live MySQL database. "
        "Every statement is parameterised and is shown as it runs, so you can "
        "verify exactly what the application does. Changes commit immediately "
        "and the dashboard refreshes."
    )

    _show_flash()
    _show_recent_write()

    try:
        live_ok = crud.count_rows("customers") >= 0
    except crud.CrudError as exc:
        live_ok = False
        st.error(f"Live MySQL connection error: {redact.redact(exc)}")

    top_left, top_mid, top_right = st.columns([1, 1, 2])
    with top_left:
        if st.button("🔄 Refresh data", use_container_width=True):
            _refresh_after_write()
            st.rerun()
    with top_mid:
        if live_ok:
            st.success("● Live MySQL connected")
        else:
            st.error("● MySQL unavailable")

    st.divider()

    read_tab, create_tab, update_tab, delete_tab = st.tabs(
        ["🔍 Read", "➕ Create", "✏️ Update", "🗑️ Delete"]
    )

    with read_tab:
        _render_show_tab()
    with create_tab:
        _render_add_tab()
    with update_tab:
        _render_update_tab()
    with delete_tab:
        _render_delete_tab()


def render_sql_query_inspector() -> None:
    """Read-only viewer for the SQL the application actually executed."""

    st.header("SQL Query Inspector")
    st.caption(
        "Every SQL statement RouteSense runs is captured here: the real "
        "template, its bound parameters, status, duration, rows and timestamp. "
        "The viewer is read-only — you cannot type SQL here — and it never "
        "shows credentials or connection strings."
    )

    history = sql_inspector.get_session_history()

    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("🧹 Clear history", use_container_width=True):
            sql_inspector.clear_history()
            st.session_state.pop("dm_last_write", None)
            st.rerun()

    if not history:
        st.info(
            "No SQL has been executed yet in this session. Open the Database "
            "Management screen or any dashboard page to generate queries."
        )
        return

    total = len(history)
    errors = sum(1 for entry in history if entry.get("status") != "success")
    durations = [
        entry.get("duration_ms", 0)
        for entry in history
        if entry.get("duration_ms") is not None
    ]
    average = sum(durations) / len(durations) if durations else 0.0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Statements captured", f"{total:,}")
    m2.metric("Failed", f"{errors:,}")
    m3.metric("Avg duration", f"{average:.1f} ms")
    m4.metric("Most recent", history[-1].get("operation", "-"))

    with st.expander("Raw history table"):
        st.dataframe(
            pd.DataFrame(history), use_container_width=True, hide_index=True
        )

    st.divider()

    operations = ["All"] + sorted({str(e.get("operation", "?")) for e in history})
    f1, f2 = st.columns(2)
    operation_filter = f1.selectbox("Operation", operations, key="sqli_op")
    status_filter = f2.selectbox(
        "Status", ["All", "success", "error"], key="sqli_status"
    )

    view = list(reversed(history))
    if operation_filter != "All":
        view = [e for e in view if str(e.get("operation")) == operation_filter]
    if status_filter != "All":
        view = [e for e in view if e.get("status") == status_filter]

    if not view:
        st.info("No statements match the current filter.")
        return

    st.caption(f"Showing {len(view):,} of {total:,} captured statements (newest first).")

    for index, entry in enumerate(view):
        icon = "✅" if entry.get("status") == "success" else "❌"
        title = " · ".join(
            part
            for part in (
                f"{icon} {entry.get('operation', 'SQL')}",
                entry.get("label", "") or "query",
                f"{entry.get('duration_ms', '?')} ms",
                entry.get("timestamp", ""),
            )
            if part
        )
        with st.expander(title, expanded=(index == 0)):
            _render_query_card(entry)


# -----------------------------------------------------------------------------
# Main application
# -----------------------------------------------------------------------------


def main() -> None:

    st.title("🚚 RouteSense")
    st.caption(
        "Last-Mile Delivery Intelligence & Route Risk Analysis"
    )

    # -------------------------------------------------------------------------
    # SQL connection: primary dependency
    # -------------------------------------------------------------------------

    sql_error: Optional[str] = None
    mongo_error: Optional[str] = None

    try:
        df = load_sql_data()
        sql_available = True
    except Exception as exc:
        df = pd.DataFrame()
        sql_available = False
        sql_error = redact.redact(str(exc))

    # -------------------------------------------------------------------------
    # MongoDB connection: optional dependency
    # -------------------------------------------------------------------------

    try:
        collection = load_mongo_collection()
        mongo_available = True
    except Exception as exc:
        collection = None
        mongo_available = False
        mongo_error = redact.redact(str(exc))

    # -------------------------------------------------------------------------
    # Sidebar
    # -------------------------------------------------------------------------

    st.sidebar.title("RouteSense")
    st.sidebar.caption("Delivery Intelligence Platform")

    page = st.sidebar.radio(
        "Navigation",
        [
            "Overview",
            "Failure Analysis",
            "Route Hotspots",
            "Route Explorer",
            "System Status",
            "Database Management",
            "SQL Query Inspector",
        ],
    )

    st.sidebar.divider()

    if sql_available:
        st.sidebar.success("MySQL ● Connected")
    else:
        st.sidebar.error("MySQL ● Unavailable")

    if mongo_available:
        st.sidebar.success("MongoDB ● Connected")
    else:
        st.sidebar.warning("MongoDB ● Unavailable")

    # -------------------------------------------------------------------------
    # If SQL is unavailable, keep the application alive and show diagnostics.
    # -------------------------------------------------------------------------

    if not sql_available:

        st.error("RouteSense could not connect to the MySQL database.")

        st.write(
            "The application is still running, but the SQL-backed dashboard "
            "cannot display data until the database connection is restored."
        )

        with st.expander("Technical error details"):
            st.code(sql_error or "Unknown MySQL error")

        if not mongo_available:
            st.warning(
                "MongoDB is also unavailable. Check the System Status page "
                "after restoring MySQL."
            )

        return

    # -------------------------------------------------------------------------
    # Overview
    # -------------------------------------------------------------------------

    if page == "Overview":

        # SQL is authoritative for the core delivery-attempt KPIs.
        sql_kpis = calculate_sql_kpis(df)

        mongo_kpis = None
        if mongo_available:
            try:
                mongo_kpis = get_kpis(collection)
            except Exception as exc:
                mongo_available = False
                mongo_error = redact.redact(str(exc))
                st.sidebar.warning("MongoDB ● Unavailable")

        st.header("Delivery Overview")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Total Attempts",
            format_number(sql_kpis["total_attempts"]),
        )

        c2.metric(
            "Failed Attempts",
            format_number(sql_kpis["failed_attempts"]),
        )

        c3.metric(
            "Delivered Attempts",
            format_number(sql_kpis["delivered_attempts"]),
        )

        c4.metric(
            "Failure Rate",
            f"{sql_kpis['failure_rate']:.2f}%",
        )

        st.divider()
        st.subheader("Data Integration Status")

        q1, q2, q3, q4 = st.columns(4)

        q1.metric(
            "SQL Attempts",
            format_number(len(df)),
        )

        if mongo_available:
            try:
                mongo_records = collection.count_documents({})
                unique_events = len(collection.distinct("event_id"))
            except Exception as exc:
                mongo_records = None
                unique_events = None
                mongo_available = False
                mongo_error = redact.redact(str(exc))
        else:
            mongo_records = None
            unique_events = None

        if mongo_records is not None:
            q2.metric(
                "MongoDB Events",
                format_number(mongo_records),
            )
        else:
            q2.metric("MongoDB Events", "Unavailable")

        if unique_events is not None:
            q3.metric(
                "Unique Event IDs",
                format_number(unique_events),
            )
        else:
            q3.metric("Unique Event IDs", "Unavailable")

        duplicate_attempts = (
            int(df["attempt_id"].duplicated().sum())
            if "attempt_id" in df.columns
            else 0
        )

        q4.metric(
            "Duplicate Attempt IDs",
            format_number(duplicate_attempts),
        )

        if mongo_available:
            st.success(
                "✅ MySQL is available and MongoDB Atlas is connected."
            )
            st.caption(
                "MongoDB event totals are reported separately from SQL "
                "attempt totals because an event stream and a relational "
                "attempt table need not contain the same number of records."
            )
        else:
            st.warning(
                "⚠️ MySQL analytics are available, but MongoDB Atlas is "
                "currently unavailable. Mongo-dependent analytics will use "
                "SQL fallback calculations where possible."
            )

        st.divider()
        st.subheader("Failure Overview")

        if mongo_available:
            try:
                failure_df = mongo_failure_summary(collection)
            except Exception:
                failure_df = calculate_sql_failure_summary(df)
                st.info("Using SQL fallback for failure analytics.")
        else:
            failure_df = calculate_sql_failure_summary(df)

        if not failure_df.empty:
            display_failure = failure_df.rename(
                columns={
                    "_id": "Failure Reason",
                    "failure_reason": "Failure Reason",
                    "failure_count": "Failures",
                    "failures": "Failures",
                    "average_delay": "Average Delay (min)",
                    "maximum_delay": "Maximum Delay (min)",
                }
            ).copy()

            display_failure = safe_round(
                display_failure,
                [
                    "Average Delay (min)",
                    "Maximum Delay (min)",
                ],
            )

            if "Failures" in display_failure.columns:
                chart_source = display_failure[
                    ["Failure Reason", "Failures"]
                ].set_index("Failure Reason")
                st.bar_chart(chart_source)

            st.dataframe(
                display_failure,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No failure records found.")

        st.divider()
        st.subheader("Hourly Failure Rate")

        if mongo_available:
            try:
                hourly_df = mongo_hourly_summary(collection)
            except Exception:
                hourly_df = calculate_sql_hourly_summary(df)
        else:
            hourly_df = calculate_sql_hourly_summary(df)

        if not hourly_df.empty:

            if "_id" in hourly_df.columns:
                hourly_df["Hour"] = pd.to_numeric(
                    hourly_df["_id"], errors="coerce"
                )
            elif "hour" in hourly_df.columns:
                hourly_df["Hour"] = pd.to_numeric(
                    hourly_df["hour"], errors="coerce"
                )
            else:
                hourly_df["Hour"] = pd.Series(
                    range(len(hourly_df)), index=hourly_df.index
                )

            if "total_attempts" not in hourly_df.columns and "attempts" in hourly_df.columns:
                hourly_df["total_attempts"] = hourly_df["attempts"]

            if "failed_attempts" not in hourly_df.columns and "failures" in hourly_df.columns:
                hourly_df["failed_attempts"] = hourly_df["failures"]

            if "failure_rate" not in hourly_df.columns:
                hourly_df["failure_rate"] = (
                    hourly_df["failed_attempts"]
                    / hourly_df["total_attempts"]
                    * 100
                ).fillna(0)

            hourly_df["Hour Label"] = hourly_df["Hour"].apply(
                lambda x: f"{int(x):02d}:00"
                if pd.notna(x)
                else "Unknown"
            )

            hourly_chart = (
                hourly_df[["Hour", "failure_rate"]]
                .dropna(subset=["Hour"])
                .sort_values("Hour")
                .set_index("Hour")
                .rename(columns={"failure_rate": "Failure Rate (%)"})
            )

            if not hourly_chart.empty:
                st.line_chart(
                    hourly_chart,
                    use_container_width=True,
                )

            top_hours = (
                hourly_df[
                    [
                        "Hour Label",
                        "total_attempts",
                        "failed_attempts",
                        "failure_rate",
                    ]
                ]
                .sort_values(
                    "failure_rate",
                    ascending=False,
                )
                .head(5)
                .rename(
                    columns={
                        "Hour Label": "Hour",
                        "total_attempts": "Attempts",
                        "failed_attempts": "Failures",
                        "failure_rate": "Failure Rate (%)",
                    }
                )
            )

            top_hours["Failure Rate (%)"] = (
                pd.to_numeric(
                    top_hours["Failure Rate (%)"],
                    errors="coerce",
                )
                .fillna(0)
                .round(2)
            )

            st.write("Highest observed hourly failure rates")
            st.dataframe(
                top_hours,
                use_container_width=True,
                hide_index=True,
            )

        else:
            st.info("No hourly attempt data available.")

    # -------------------------------------------------------------------------
    # Failure Analysis
    # -------------------------------------------------------------------------

    elif page == "Failure Analysis":

        st.header("Failure Analysis")

        if mongo_available:
            try:
                failure_df = mongo_failure_summary(collection)
            except Exception:
                failure_df = calculate_sql_failure_summary(df)
                st.info("MongoDB analytics unavailable — using SQL fallback.")
        else:
            failure_df = calculate_sql_failure_summary(df)
            st.info("MongoDB unavailable — using SQL fallback.")

        if failure_df.empty:
            st.warning("No failure records found.")
        else:

            display_failure = failure_df.rename(
                columns={
                    "_id": "Failure Reason",
                    "failure_reason": "Failure Reason",
                    "failure_count": "Failures",
                    "failures": "Failures",
                    "average_delay": "Average Delay (min)",
                    "maximum_delay": "Maximum Delay (min)",
                }
            ).copy()

            c1, c2 = st.columns(2)

            c1.metric(
                "Failure Categories",
                len(display_failure),
            )

            total_failures = (
                display_failure["Failures"].sum()
                if "Failures" in display_failure.columns
                else 0
            )

            c2.metric(
                "Failed Attempts",
                format_number(total_failures),
            )

            st.divider()

            if "Failure Reason" in display_failure.columns and "Failures" in display_failure.columns:
                st.bar_chart(
                    display_failure[
                        ["Failure Reason", "Failures"]
                    ].set_index("Failure Reason")
                )

            display_failure = safe_round(
                display_failure,
                [
                    "Average Delay (min)",
                    "Maximum Delay (min)",
                ],
            )

            st.dataframe(
                display_failure,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download Failure Analysis",
                display_failure.to_csv(
                    index=False
                ).encode("utf-8"),
                "failure_analysis.csv",
                "text/csv",
            )

    # -------------------------------------------------------------------------
    # Route Hotspots
    # -------------------------------------------------------------------------

    elif page == "Route Hotspots":

        st.header("Route Hotspots")
        st.caption(
            "Route scores combine failure rate, repeat-failure rate and order volume."
        )

        if mongo_available:
            try:
                hotspot_df = mongo_route_hotspots(collection)
            except Exception:
                hotspot_df = calculate_sql_route_hotspots(df)
                st.info("MongoDB analytics unavailable — using SQL fallback.")
        else:
            hotspot_df = calculate_sql_route_hotspots(df)
            st.info("MongoDB unavailable — using SQL fallback.")

        if hotspot_df.empty:
            st.warning("No hotspot data available.")
        else:

            min_orders = st.slider(
                "Minimum Orders",
                min_value=100,
                max_value=5000,
                value=100,
                step=100,
            )

            filtered = hotspot_df[
                hotspot_df["total_orders"] >= min_orders
            ].copy()

            filtered = filtered.rename(
                columns={
                    "_id": "Route",
                    "total_orders": "Orders",
                    "failed_orders": "Failed Orders",
                    "repeat_failure_orders": "Repeat Failure Orders",
                    "failure_rate": "Failure Rate (%)",
                    "repeat_failure_rate": "Repeat Failure Rate (%)",
                    "hotspot_score": "Hotspot Score",
                }
            )

            filtered = safe_round(
                filtered,
                [
                    "Failure Rate (%)",
                    "Repeat Failure Rate (%)",
                    "Hotspot Score",
                ],
            )

            st.metric(
                "Routes Displayed",
                len(filtered),
            )

            st.dataframe(
                filtered,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download Route Hotspots",
                filtered.to_csv(
                    index=False
                ).encode("utf-8"),
                "route_hotspots.csv",
                "text/csv",
            )

    # -------------------------------------------------------------------------
    # Route Explorer
    # -------------------------------------------------------------------------

    elif page == "Route Explorer":

        st.header("Route Explorer")

        if "route_id" not in df.columns:
            st.warning("Route information is unavailable in the SQL dataset.")
            return

        routes = sorted(
            df["route_id"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        if not routes:
            st.warning("No route data available.")
            return

        selected_route = st.selectbox(
            "Select Route",
            routes,
        )

        route_data = df[
            df["route_id"].astype(str) == selected_route
        ].copy()

        total_orders, failed_orders, failure_rate = (
            route_explorer_failure_rates(route_data)
        )

        if route_data.empty:
            st.warning("No data found for the selected route.")
            return

        metadata = route_data.iloc[0]

        route_hotspot = None

        if mongo_available:
            try:
                hotspot_results = get_route_hotspots(collection)
                route_hotspot = next(
                    (
                        item
                        for item in hotspot_results
                        if str(item.get("_id")) == selected_route
                    ),
                    None,
                )
            except Exception:
                route_hotspot = None

        if route_hotspot is None:
            sql_hotspots = calculate_sql_route_hotspots(df)
            if not sql_hotspots.empty:
                match = sql_hotspots[
                    sql_hotspots["_id"].astype(str) == selected_route
                ]
                if not match.empty:
                    route_hotspot = match.iloc[0].to_dict()

        route_name = metadata.get(
            "route_name",
            "Unknown Route",
        )

        st.subheader(
            f"{selected_route} — {route_name}"
        )

        r1, r2, r3, r4 = st.columns(4)

        r1.metric(
            "Orders",
            format_number(total_orders),
        )

        r2.metric(
            "Failed Orders",
            format_number(failed_orders),
        )

        r3.metric(
            "Failure Rate",
            f"{failure_rate:.2f}%",
        )

        if route_hotspot:
            r4.metric(
                "Hotspot Score",
                f"{float(route_hotspot.get('hotspot_score', 0)):.2f}",
            )
        else:
            r4.metric("Hotspot Score", "N/A")

        if route_hotspot:
            st.divider()

            h1, h2 = st.columns(2)

            h1.metric(
                "Repeat Failure Rate",
                f"{float(route_hotspot.get('repeat_failure_rate', 0)):.2f}%",
            )

            h2.metric(
                "Repeat Failure Orders",
                format_number(
                    route_hotspot.get(
                        "repeat_failure_orders",
                        0,
                    )
                ),
            )

        st.divider()

        info1, info2, info3, info4 = st.columns(4)

        info1.write(
            f"**Zone:** {metadata.get('order_zone', 'N/A')}"
        )

        info2.write(
            f"**Origin Hub:** {metadata.get('origin_hub', 'N/A')}"
        )

        info3.write(
            f"**Driver:** {metadata.get('driver_name', 'N/A')}"
        )

        info4.write(
            f"**Vehicle:** {metadata.get('vehicle_type', 'N/A')}"
        )

        st.divider()
        st.subheader("Failure Reasons")

        if "attempt_status" not in route_data.columns:
            st.info("Attempt status is unavailable.")
            return

        reasons = (
            route_data.loc[
                route_data["attempt_status"] == "Failed",
                "failure_reason",
            ]
            .fillna("Unknown")
            .astype(str)
            .value_counts()
        )

        if reasons.empty:
            st.info("No failures recorded for this route.")
        else:
            st.bar_chart(reasons)
            st.dataframe(
                reasons.rename("Failures").reset_index().rename(
                    columns={"failure_reason": "Failure Reason"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    # -------------------------------------------------------------------------
    # System Status
    # -------------------------------------------------------------------------

    elif page == "System Status":

        st.header("System Status")

        st.subheader("Database Connectivity")

        c1, c2 = st.columns(2)

        with c1:
            if sql_available:
                st.success("● MySQL — Connected")
                st.write("Database: `delivery_db`")
            else:
                st.error("● MySQL — Unavailable")
                with st.expander("MySQL error"):
                    st.code(sql_error or "Unknown MySQL error")

        with c2:
            if mongo_available:
                st.success("● MongoDB Atlas — Connected")
                st.write("Database: `routesense`")
                st.write("Collection: `delivery_events`")
            else:
                st.warning("● MongoDB Atlas — Unavailable")
                with st.expander("MongoDB error"):
                    st.code(mongo_error or "Unknown MongoDB error")

        st.divider()
        st.subheader("Dataset Integrity")

        sql_rows = len(df)
        duplicate_attempt_ids = (
            int(df["attempt_id"].duplicated().sum())
            if "attempt_id" in df.columns
            else 0
        )

        mongo_rows = None
        unique_events = None

        if mongo_available:
            try:
                mongo_rows = collection.count_documents({})
                unique_events = len(
                    collection.distinct("event_id")
                )
            except Exception as exc:
                mongo_error = redact.redact(str(exc))
                mongo_available = False

        checks = [
            (
                "SQL delivery-attempt rows",
                sql_rows > 0,
                f"{sql_rows:,}",
            ),
            (
                "No missing order IDs",
                "order_id" in df.columns
                and int(df["order_id"].isna().sum()) == 0,
                None,
            ),
            (
                "No missing route IDs",
                "route_id" in df.columns
                and int(df["route_id"].isna().sum()) == 0,
                None,
            ),
            (
                "No duplicate attempt IDs",
                duplicate_attempt_ids == 0,
                None,
            ),
        ]

        for name, passed, value in checks:
            if passed:
                message = f"✅ {name}"
                if value:
                    message += f" — {value}"
                st.success(message)
            else:
                st.error(f"❌ {name}")

        if mongo_available:
            st.success(
                f"✅ MongoDB event documents — {mongo_rows:,}"
            )
            st.success(
                f"✅ Unique event IDs — {unique_events:,}"
            )
        else:
            st.warning(
                "⚠️ MongoDB integrity checks unavailable because the Atlas "
                "connection is currently down."
            )

        st.divider()
        st.subheader("Dataset Summary")

        s1, s2, s3 = st.columns(3)

        s1.metric(
            "SQL Attempt Rows",
            f"{sql_rows:,}",
        )

        s2.metric(
            "MongoDB Events",
            f"{mongo_rows:,}" if mongo_rows is not None else "Unavailable",
        )

        s3.metric(
            "Unique Event IDs",
            f"{unique_events:,}" if unique_events is not None else "Unavailable",
        )

    # -------------------------------------------------------------------------
    # Database Management (Create / Read / Update / Delete)
    # -------------------------------------------------------------------------

    elif page == "Database Management":

        # Admin gate: protects every CRUD control and record read. No database
        # query from this page runs until authentication succeeds.
        if _require_admin():
            render_database_management()

    # -------------------------------------------------------------------------
    # SQL Query Inspector (read-only view of executed statements)
    # -------------------------------------------------------------------------

    elif page == "SQL Query Inspector":

        render_sql_query_inspector()


if __name__ == "__main__":
    main()
