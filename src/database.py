import os

import mysql.connector
import pandas as pd
from dotenv import load_dotenv

try:  # Normal package import (``from src.database import ...``).
    from src import sql_inspector
    from src import tls
except ImportError:  # pragma: no cover - allows ``python src/database.py``.
    import sql_inspector
    import tls

# Load a local ``.env`` for developer convenience only. Real process
# environment variables and Streamlit secrets (bridged into the environment by
# ``app.load_streamlit_secrets``) always take precedence, so a stray ``.env``
# can never silently override deployed configuration.
load_dotenv(override=False)


QUERY = """
SELECT
    o.order_id,
    o.olist_order_id,
    o.customer_id,
    o.route_id,
    o.order_date,
    o.promised_date,
    o.delivery_date,
    o.status AS order_status,
    o.amount,
    o.freight_value,
    o.zone AS order_zone,

    c.customer_unique_id,
    c.city,
    c.zone AS customer_zone,
    c.region,
    c.pincode,

    r.route_name,
    r.origin_hub,
    r.distance_km,
    r.driver_id,
    r.vehicle_id,

    d.name AS driver_name,
    d.experience_years,

    v.vehicle_type,
    v.capacity_kg,

    da.attempt_id,
    da.attempt_no,
    da.attempt_time,
    da.status AS attempt_status,
    da.failure_reason,
    da.delay_minutes

FROM delivery_attempts da

JOIN orders o
    ON da.order_id = o.order_id

JOIN customers c
    ON o.customer_id = c.customer_id

JOIN routes r
    ON o.route_id = r.route_id

JOIN drivers d
    ON r.driver_id = d.driver_id

JOIN vehicles v
    ON r.vehicle_id = v.vehicle_id
"""


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a clear error message."""

    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got a non-numeric value.") from exc


def get_mysql_connection():
    password = os.getenv("ROUTESENSE_MYSQL_PASSWORD")

    if not password:
        raise RuntimeError(
            "ROUTESENSE_MYSQL_PASSWORD is not configured."
        )

    connect_kwargs = {
        "host": os.getenv(
            "ROUTESENSE_MYSQL_HOST",
            "localhost"
        ),
        "port": _env_int("ROUTESENSE_MYSQL_PORT", 3306),
        "user": os.getenv(
            "ROUTESENSE_MYSQL_USER",
            "root"
        ),
        "password": password,
        "database": os.getenv(
            "ROUTESENSE_MYSQL_DATABASE",
            "delivery_db"
        ),
    }

    # Optional TLS: required by some managed hosts (e.g. Aiven). Point
    # ROUTESENSE_MYSQL_SSL_CA at the provider's CA ``.pem`` **path** or paste its
    # PEM **content** (e.g. via Streamlit secrets). Left unset, the connector
    # negotiates TLS automatically and behaviour is unchanged for local/Railway.
    ssl_ca = os.getenv("ROUTESENSE_MYSQL_SSL_CA")
    if ssl_ca:
        connect_kwargs["ssl_ca"] = tls.resolve_ca(ssl_ca)
        connect_kwargs["ssl_verify_cert"] = True

    return mysql.connector.connect(**connect_kwargs)


def load_integrated_data():
    conn = get_mysql_connection()

    try:
        rows = sql_inspector.execute(
            conn,
            QUERY,
            (),
            fetch=True,
            dictionary=True,
            label="Integrated delivery dataset (analytics)",
            operation="SELECT",
        )

        return pd.DataFrame(rows)

    finally:
        conn.close()


if __name__ == "__main__":
    df = load_integrated_data()
    print(df["attempt_status"].value_counts(dropna=False))
    