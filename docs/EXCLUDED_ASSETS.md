# Excluded assets (intentional, documented)

This document explains why certain artifacts from the original RouteSense repository were not published here.

| Asset | Type | Rationale |
|---|---|---|
| `data/raw/*.csv` | Third-party (Olist) | Public Kaggle dataset (CC BY-NC-SA 4.0). Not redistributed in bulk; documented in `data/README.md` with acquisition instructions. |
| `data/cleaned/*` | Derived | Can be regenerated from raw sources; excluded to avoid redistributing derived third-party data. |
| `data/analytics/*` | Aggregates | Example analytics outputs; regenerable by the app; likely stale relative to dataset evolution. |
| `data/Data.zip` | Bundle | Stale historical snapshot (corresponds to an older dataset with ~117,916 delivery attempts) — superseded by the current synthetic sources and is not treated as authoritative. |
| `mongodb/delivery_events.json` | Large JSON (184 MB) | Not required for the public runtime or reproducibility of the core SQL features; excluded by size and scope. |
| `sql/delivery_db_backup.sql` | SQL dump (30 MB, stale) | Older export with inconsistent counts; explicitly not authoritative. Excluded. |
| `railway.exe` | Binary (17.8 MB) | Deployment-specific artifact; unnecessary for local development. |
| `check_counts.py`, `import_backup.py`, `import_railway.py`, `migrate_data.py`, `migrate_schema.py`, `repair_attempt_status.py`, `restore_attempts.py` | One-off migration/repair | Targeted local/railway migration tooling that references private deployment details; not part of the public runtime, schema, tests or reproducible setup. |
| `src/analytics.py` | Legacy module | Not imported by `app.py` in this hardened branch; functionality is represented elsewhere or excluded intentionally. |
| `Procfile` | Platform config | Platform-specific deployment file, not required for local execution. |

These exclusions preserve privacy, reduce repo size, avoid publishing stale/production artifacts, and keep the public repository focused on reproducible code and a safe synthetic/demo dataset.
