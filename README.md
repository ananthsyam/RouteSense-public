# RouteSense

A Streamlit dashboard for last-mile delivery analytics. It reads a MySQL
warehouse (customers, orders, routes, drivers, vehicles, delivery attempts) and
optionally a MongoDB Atlas collection of delivery events.

This repository is a **public deployment copy** of the RouteSense Streamlit app.
It contains no credentials: all configuration is supplied through environment
variables or Streamlit **Secrets**.

## Features

- **Delivery Overview** — totals, delivered vs failed, on-time performance
- **Failure Analysis** — failure reasons and affected zones
- **Route Hotspots** — routes ranked by delivery failures
- **Route Explorer** — drill into a single route
- **System Status** — live MySQL / MongoDB health
- **Database Management** — CRUD (create / read / update / delete) for the six core tables
- **SQL Query Inspector** — run and review real SQL against the connected database
- **MongoDB event analytics** — with a SQL fallback when Atlas is unavailable

## Requirements

- Python 3.11+
- A MySQL 8.x database (TLS-capable, e.g. Aiven)
- Optional: MongoDB Atlas (the app falls back to SQL if it is unavailable)

## Configuration

All configuration is read from environment variables. On Streamlit Community
Cloud, values placed in **Secrets** are copied into the environment by `app.py`.

| Variable | Purpose |
|---|---|
| `ROUTESENSE_MYSQL_HOST` | MySQL host |
| `ROUTESENSE_MYSQL_PORT` | MySQL port |
| `ROUTESENSE_MYSQL_USER` | MySQL user |
| `ROUTESENSE_MYSQL_PASSWORD` | MySQL password (**required**) |
| `ROUTESENSE_MYSQL_DATABASE` | MySQL database name (default `delivery_db`) |
| `ROUTESENSE_MYSQL_SSL_CA` | Optional CA certificate for verified TLS — a file path, or the PEM content itself |
| `ROUTESENSE_ATLAS_URI` | MongoDB Atlas connection string |
| `ROUTESENSE_ATLAS_USER` | MongoDB Atlas user |
| `ROUTESENSE_ATLAS_PASSWORD` | MongoDB Atlas password |
| `ROUTESENSE_MONGODB_DATABASE` | MongoDB database (default `routesense`) |
| `ROUTESENSE_MONGODB_COLLECTION` | MongoDB collection (default `delivery_events`) |
| `ROUTESENSE_ADMIN_PASSWORD` | Password that unlocks the **Database Management** (CRUD) page. If unset or empty, CRUD stays locked (fail closed). |

No credentials are stored in this repository.

### Protecting database writes

The **Database Management** page (create / read / update / delete) is gated
behind `ROUTESENSE_ADMIN_PASSWORD`. If the secret is missing or empty the page
is locked and **no CRUD controls and no database records are rendered**.

Authentication uses a constant-time comparison; only a boolean session flag is
stored — the password itself is never kept, printed or committed. A Logout
button clears the flag.

The analytics pages and the read-only **SQL Query Inspector** stay public. The
Inspector shows only the statements executed in the current visitor's own
session, and credentials / connection details are redacted before storage.

### TLS

Managed MySQL providers commonly require a CA certificate. Set
`ROUTESENSE_MYSQL_SSL_CA` to a `.pem` **path** when running locally, or paste the
PEM **content** into Streamlit Secrets (the app writes it to a private temporary
file). Certificate verification is never disabled.

## Run locally

```bash
pip install -r requirements.txt
set ROUTESENSE_MYSQL_HOST=127.0.0.1
set ROUTESENSE_MYSQL_PORT=3306
set ROUTESENSE_MYSQL_USER=root
set ROUTESENSE_MYSQL_PASSWORD=change-me
set ROUTESENSE_MYSQL_DATABASE=delivery_db
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this directory to a GitHub repository.
2. <https://share.streamlit.io> → **New app** → select the repo, branch, and
   main file `app.py`.
3. **Settings → Secrets** → add the variables above, e.g.:

```toml
ROUTESENSE_MYSQL_HOST = "<host>"
ROUTESENSE_MYSQL_PORT = "<port>"
ROUTESENSE_MYSQL_USER = "<user>"
ROUTESENSE_MYSQL_PASSWORD = "<password>"
ROUTESENSE_MYSQL_DATABASE = "<database>"
ROUTESENSE_MYSQL_SSL_CA = """-----BEGIN CERTIFICATE-----
...provider CA certificate...
-----END CERTIFICATE-----
"""
ROUTESENSE_ATLAS_URI = "mongodb+srv://..."
ROUTESENSE_ATLAS_USER = "<user>"
ROUTESENSE_ATLAS_PASSWORD = "<password>"
```

## Tests

```bash
python -m pytest tests -q
```

## Notes

- Free-tier managed MySQL services may power off when idle; the app reports a
  clear connection error and recovers on the next attempt once the database is
  awake.
- `streamlit` is pinned because the UI uses `use_container_width`, which is
  deprecated in newer Streamlit releases.
