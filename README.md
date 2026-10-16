# RouteSense — Delivery Intelligence & Route Risk Analysis

RouteSense is a Streamlit application for last-mile delivery analytics, built for the DCDS project. It combines structured relational data (MySQL) with optional event data (MongoDB Atlas) to help explore delivery performance, identify failure patterns and hotspots, and inspect the database directly through a controlled CRUD interface with visible SQL execution.

## 1. Project Overview

RouteSense analyses operational delivery data across customers, orders, routes, drivers, vehicles and delivery attempts. The application presents interactive dashboards for delivery overview, failure analysis, route hotspots and route exploration. A System Status page surfaces live connectivity, and a gated Database Management page provides controlled write access to the six core tables. The SQL Query Inspector makes the application's executed SQL (templates and bound parameters) visible for each read query, supporting transparency and reproducibility.

**Key goals:**
- Make delivery performance measurable and explorable via interactive charts.
- Enforce a fail-closed administrative boundary for write operations.
- Make database execution visible (parameterised SQL, session-isolated history, redaction) without exposing an arbitrary SQL console.
- Remain reproducible with a small, deterministic demo dataset and automated validation.

## 2. Features

| Page/Capability | Description |
|---|---|
| **Delivery Overview** | Summarises totals, delivered vs failed, and on-time performance for the loaded dataset. |
| **Failure Analysis** | Breaks down failure reasons by zone and volume to surface recurring issues. |
| **Route Hotspots** | Ranks routes by delivery failures to highlight operational risk areas. |
| **Route Explorer** | Drills into a specific route to inspect delivery outcomes in context. |
| **System Status** | Reports live MySQL and MongoDB Atlas connectivity, the effective database/collection names, and connection errors when present. |
| **Database Management (CRUD)** | Authenticated Create/Read/Update/Delete for all six core tables. Gated by administrator password; only a boolean flag is stored in session state. Includes search, filtering, pagination and deletion confirmation. |
| **SQL Query Inspector** | Displays the exact SQL templates and bound parameters executed by the application for read operations, with timing and affected-row counts. Session-isolated and redacted. Not an arbitrary SQL console. |
| **MongoDB Atlas Integration** | Optionally loads delivery events from MongoDB Atlas; gracefully falls back to SQL-derived analytics when Atlas is unavailable. |

## 3. Technology Stack

| Technology | Purpose |
|---|---|
| **Python** | Application logic and data processing. |
| **Streamlit** | Interactive web UI and session state management. |
| **MySQL 8.x** | Relational warehouse for customers, orders, routes, drivers, vehicles and delivery attempts. |
| **MySQL Connector/Python** | TLS-aware MySQL connectivity used by the application. |
| **MongoDB Atlas** | Optional event store for delivery-event analytics. |
| **PyMongo** | MongoDB client used when Atlas is configured and reachable. |
| **pandas** | Tabular data manipulation and rendering. |
| **python-dotenv** | Local environment loading for development convenience (does not override deployed secrets). |
| **pytest** | Automated unit/integration tests. |

## 4. Architecture

```mermaid
flowchart LR
    U[User] -->|Browser| S[Streamlit App]
    S -->|Analytics| M[MySQL: core tables]
    S -->|Event analytics| A[MongoDB Atlas]
    S -->|CRUD (gated)| M
    S -->|SQL Query Inspector| I[SQL execution instrumentation]
    I -->|parameterised SQL + metrics| S
    Auth[Admin Auth (fail-closed)] -->|session flag only| S
    A -.fallback.-> S
```

**Data flow:** Users interact with Streamlit pages. Read operations build parameterised SQL via `src/crud.py` and execute through `src/sql_inspector.py`, which records templates/parameters (redacted) per session. Write operations (CRUD) are blocked until authenticated via `src/auth.py` (fail-closed; constant-time comparison; session-scoped lockout and idle expiry). MySQL connectivity is handled by `src/database.py` with TLS verification via `src/tls.py`. MongoDB access is handled by `src/mongodb.py` with graceful degradation to SQL.

## 5. Database Design

RouteSense uses six core relational tables (see `sql/schema.sql`). Foreign keys enforce referential integrity; enums constrain status values.

| Table | Purpose | Key Relationships |
|---|---|---|
| `customers` | Customer identity, location (city/zone/region/pincode) | Referenced by `orders.customer_id` (FK). |
| `drivers` | Driver identity, licence and experience | Referenced by `routes.driver_id` (FK). |
| `vehicles` | Vehicle type/capacity and registration | Referenced by `routes.vehicle_id` (FK). |
| `routes` | Route definition, zone/origin, distance, assigned driver/vehicle | Referenced by `orders.route_id` (FK). |
| `orders` | Order lifecycle (dates, status, amount/freight, zone) | References `customers` and `routes`; referenced by `delivery_attempts.order_id` (FK). |
| `delivery_attempts` | Attempt-level outcomes (attempt_no, time, status, failure reason, delay minutes) | References `orders`. |

**Status mapping (source → schema):** `SUCCESS` → `Delivered`, `FAILED` → `Failed`. Order status values used by the application align with the schema enums (`Delivered`, `Failed`, `Pending`, `In Transit`).

MySQL attempts and MongoDB delivery events are separate data sources (different schemas/counting semantics). The application does not assume they must match; MongoDB analytics fall back to SQL when unavailable.

## 6. Data Assets & Integrity

Data provenance and what's included/excluded is documented in `data/README.md` and `data/manifest.json`. Integrity is enforced by `scripts/validate_data.py` and tested by `tests/test_data_integrity.py`.

**Committed (safe, reproducible):**
- `data/synthetic/` — synthetic source assets (`drivers.csv`, `vehicles.csv`, `routes.csv`, `delivery_attempts.csv`). These are privacy-safe and match documented targets for the four tables.
- `data/demo/` — deterministic, DB-ready synthetic demo (300 orders + related, 324 attempts). Generated by `scripts/build_demo_dataset.py` for end-to-end loading via `sql/insert.sql`.

**Excluded (not committed):** raw Olist CSVs, cleaned/enriched outputs, large MongoDB JSON, stale SQL backup, and one-off migration tooling. Reasons and acquisition guidance are in `docs/EXCLUDED_ASSETS.md` and `data/README.md`.

**Verified full-dataset targets (documented):** 99,441 customers; 99,441 orders; 107,066 delivery attempts (104,103 Delivered/SUCCESS, 2,963 Failed); 270 routes; 250 drivers; 250 vehicles.

**Validate data:** `python scripts/validate_data.py` (demo) or `python scripts/validate_data.py --source-targets` (synthetic sources vs targets). Schema↔app consistency is validated automatically.

## 7. Repository Structure

```text
RouteSense-public/
├── .env.example
├── .github/workflows/ci.yml
├── app.py
├── data/
│   ├── README.md
│   ├── demo/                # deterministic DB-ready demo CSVs
│   ├── manifest.json
│   └── synthetic/           # synthetic source assets
├── docs/
│   └── EXCLUDED_ASSETS.md
├── notebooks/                # sanitized coursework notebooks
├── requirements.txt
├── requirements-dev.txt
├── scripts/
│   ├── build_demo_dataset.py
│   └── validate_data.py
├── sql/
│   ├── advanced_queries.sql
│   ├── insert.sql
│   ├── procedures.sql
│   ├── reset_database.sql
│   └── schema.sql
├── src/
│   ├── __init__.py
│   ├── auth.py               # fail-closed auth + lockout + idle expiry
│   ├── crud.py               # validated CRUD + SQL templates
│   ├── database.py           # MySQL connection + TLS
│   ├── mongodb.py            # Atlas access + fallback
│   ├── redact.py             # redaction helpers
│   ├── sql_inspector.py      # parameterised SQL instrumentation
│   └── tls.py                # CA resolution with verification
└── tests/                    # unit/integration tests + data integrity
```

## 8. Getting Started

### Prerequisites
- Python 3.12+ (tested on 3.14.5 locally; CI uses 3.12/3.13)
- MySQL 8.x (local or managed, TLS-capable)
- Optional: MongoDB Atlas

### Clone
```bash
git clone https://github.com/ananthsyam/RouteSense-public.git
cd RouteSense-public
```

### Setup environment (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for tests/validation
```

### Configure
Create a local `.env` (never committed) or configure Streamlit Secrets on deployment. See `.env.example` for the full list of environment variables. All configuration keys are documented in Section 9.

### Initialise database (local MySQL)
```sql
CREATE DATABASE IF NOT EXISTS delivery_db CHARACTER SET utf8mb4;
USE delivery_db;
source sql/schema.sql;   -- non-destructive
source sql/insert.sql;   -- loads data/demo/*.csv (requires local_infile)
```

> `sql/schema.sql` is idempotent and never drops databases/tables. For a clean rebuild in disposable environments only, use `sql/reset_database.sql` (explicitly destructive, read warnings first).

### Load/validate data
```bash
python scripts/validate_data.py           # validate demo dataset
python scripts/validate_data.py --source-targets  # verify synthetic sources
python scripts/build_demo_dataset.py --orders 300  # regenerate deterministic demo
```

### Run the app
```bash
streamlit run app.py
```

## 9. Configuration Reference

All configuration is read from environment variables. On Streamlit Community Cloud, values in Secrets are copied into the environment at startup (see `app.load_streamlit_secrets()`).

| Variable | Required | Purpose |
|---|---|---|
| `ROUTESENSE_ADMIN_PASSWORD` | Yes (to unlock CRUD) | Administrator password for Database Management. Missing/empty → CRUD locked (fail-closed). Never stored; constant-time comparison. |
| `ROUTESENSE_MYSQL_HOST` | Yes (for MySQL) | MySQL hostname. |
| `ROUTESENSE_MYSQL_PORT` | No | MySQL port (default 3306). Must be integer. |
| `ROUTESENSE_MYSQL_USER` | Yes | MySQL username. |
| `ROUTESENSE_MYSQL_PASSWORD` | Yes | MySQL password. Never logged. |
| `ROUTESENSE_MYSQL_DATABASE` | No | MySQL database name (default `delivery_db`). |
| `ROUTESENSE_MYSQL_SSL_CA` | No | TLS CA: either an existing file path, or PEM certificate content (including BEGIN/END). Certificate verification is never disabled. |
| `ROUTESENSE_ATLAS_URI` | No | MongoDB Atlas connection string. Localhost URIs are rejected by design. |
| `ROUTESENSE_ATLAS_USER` | No | MongoDB Atlas username (alternative auth form). |
| `ROUTESENSE_ATLAS_PASSWORD` | No | MongoDB Atlas password (alternative auth form). |
| `ROUTESENSE_MONGODB_DATABASE` | No | MongoDB database name (default `routesense`). |
| `ROUTESENSE_MONGODB_COLLECTION` | No | MongoDB collection name (default `delivery_events`). |

**Notes:** `.env` is ignored by Git. Real values must never be committed. TLS failures produce clear, safe messages (no secret leakage).

## 10. Authentication, CRUD & SQL Query Inspector

**Authentication:** Database Management is gated by `ROUTESENSE_ADMIN_PASSWORD`. Behaviour: fail-closed if missing/empty; constant-time comparison via `hmac.compare_digest`; session-scoped lockout after 5 consecutive failed attempts (30s); authenticated sessions auto-expire after 30 minutes of inactivity (idle expiry). Only a boolean `authenticated` flag + timestamps are stored in session state; the password is never stored, logged or returned. Logout clears all privileged session keys.

**CRUD:** Parameterised SQL, column/identifier validation against `TABLE_SPECS`, required-field and type coercion, foreign-key existence checks, duplicate-key handling, and human-readable error mapping. Delete operations require explicit confirmation. Search/filter/pagination are supported.

**SQL Query Inspector:** For read operations, `src/sql_inspector.py` records the SQL template, bound parameters (redacted via `src/redact.py`), execution status, duration and affected rows. History is **session-isolated** (never shared across browser sessions). Credentials/connection strings are never stored. The Inspector displays what the application actually executes — it is not an arbitrary SQL console.

## 11. Deployment

**Recommended stack:** Streamlit Community Cloud (app), Aiven MySQL (relational DB), MongoDB Atlas (optional events).

**Streamlit Community Cloud setup:**
1. Create a new app from `https://github.com/ananthsyam/RouteSense-public.git`.
2. Select branch `main` (or the audited branch for review) and entry point `app.py`.
3. Add required Secrets: at minimum `ROUTESENSE_ADMIN_PASSWORD` and MySQL credentials (`ROUTESENSE_MYSQL_HOST`, `ROUTESENSE_MYSQL_PORT`, `ROUTESENSE_MYSQL_USER`, `ROUTESENSE_MYSQL_PASSWORD`, `ROUTESENSE_MYSQL_DATABASE`). If using Aiven TLS, include `ROUTESENSE_MYSQL_SSL_CA` as PEM content (or file path as appropriate).
4. (Optional) Add MongoDB Atlas secrets if using event analytics.
5. Deploy and verify via System Status.

**Notes:** Free-tier services may become idle after inactivity; connectivity checks appear in System Status. No uptime/failover guarantees implied.

## 12. Testing & Quality

Run all checks locally (no production DB connections):

```bash
python -m compileall app.py src tests scripts
python -m pytest -q                # 63 tests
python scripts/validate_data.py --source-targets
```

CI (`.github/workflows/ci.yml`) runs on Python 3.12/3.13: install deps, compileall, pytest, and schema+demo validation. Tests use mocks/fakes and temporary fixtures; they do not require live database access.

## 13. Security & Privacy

- **Secrets never in Git.** `.env` ignored; `.env.example` contains placeholders only.
- **Fail-closed by default.** Missing/empty admin password blocks all CRUD.
- **Defence-in-depth:** constant-time password comparison; session-scoped lockout + idle expiry; parameterised SQL (identifier validation); TLS verification never disabled.
- **Visibility without exposure:** SQL Query Inspector records redacted, session-isolated history only.
- **Safe data handling:** private/unlicensed dataset snapshots excluded; synthetic/demo only committed. Third-party data (Olist) is not redistributed; attribution documented in `data/README.md`.
- **Least privilege guidance:** prefer a runtime DB account limited to SELECT/INSERT/UPDATE/DELETE (schema/migrations separate). This is a recommendation (not applied automatically).

## 14. License & Attribution

No `LICENSE` file is declared in this repository at this time (licensing remains unresolved pending explicit approval). Third-party materials remain subject to their respective terms:
- **Olist Brazilian E-Commerce Public Dataset** — [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Attribution required if redistributing.

## 15. Summary

RouteSense demonstrates practical database engineering: a clear relational schema, validated data integrity, parameterised SQL with transparent execution, fail-closed write protection, graceful degradation for optional services, and reproducible setup via synthetic/demo data and automated validation. All behaviour is verified against the actual codebase with no placeholders or unverified claims.
