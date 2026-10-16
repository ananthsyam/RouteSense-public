"""Validate the RouteSense schema and datasets -- no database required.

Two jobs:

1. **Schema / application consistency.** Parse ``sql/schema.sql`` and compare it
   with the schema the application actually uses
   (:data:`src.crud.TABLE_SPECS`): column names and order, primary keys,
   foreign keys, required (``NOT NULL``) columns and enum options must agree.
   Drift here is how a UI ends up showing a column the database does not have.

2. **Dataset integrity.** Check a directory of CSV files against the schema:
   expected files/columns, duplicate primary keys, missing foreign keys, empty
   required values, enum membership and the Delivered/Failed attempt totals.

It never opens a database connection and never needs a secret, so it is safe to
run in CI and on a laptop.

Usage
-----
    python scripts/validate_data.py                   # cross-check + validate data/demo
    python scripts/validate_data.py --data data/demo
    python scripts/validate_data.py --source-targets  # check bundled synthetic counts
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

#: Tables in foreign-key (load) order.
TABLE_ORDER = (
    "customers",
    "drivers",
    "vehicles",
    "routes",
    "orders",
    "delivery_attempts",
)

#: Documented targets for the *full* dataset (see data/README.md). These are
#: targets, not assumptions: whatever can be checked against a bundled local
#: source is checked by ``verify_source_targets``.
FULL_DATASET_TARGETS = {
    "customers": 99_441,
    "orders": 99_441,
    "delivery_attempts": 107_066,
    "routes": 270,
    "drivers": 250,
    "vehicles": 250,
}

#: Documented totals for the bundled synthetic attempt source (labels).
SOURCE_STATUS_TARGETS = {"SUCCESS": 104_103, "FAILED": 2_963}

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\((.*?)\)\s*;",
    re.S | re.I,
)
_ENUM_RE = re.compile(r"ENUM\s*\(([^)]*)\)", re.I)
_FK_RE = re.compile(
    r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+`?(\w+)`?\s*\(([^)]*)\)",
    re.I,
)
_PK_RE = re.compile(r"^PRIMARY\s+KEY\s*\(([^)]*)\)", re.I)
_VARCHAR_RE = re.compile(r"^VARCHAR\s*\((\d+)\)", re.I)
_SKIP_RE = re.compile(r"^(UNIQUE|KEY|INDEX|CONSTRAINT|CHECK)\b", re.I)


class ValidationError(Exception):
    """A schema or dataset problem was found."""


# ---------------------------------------------------------------------------
# Schema parsing
# ---------------------------------------------------------------------------


def _split_ident_list(value: str) -> list:
    """``"`a`, `b`"`` -> ``["a", "b"]``."""

    return [item.strip().strip("`") for item in value.split(",") if item.strip()]


def _split_quoted(value: str) -> list:
    """Extract single-quoted enum labels from ``'a','b'``."""

    return re.findall(r"'((?:[^']|'')*)'", value)


def _parse_column(line: str) -> dict | None:
    match = re.match(r"`?(\w+)`?\s+(.*)$", line)
    if not match:
        return None
    name, rest = match.group(1), match.group(2)
    upper = rest.upper()
    enum_match = _ENUM_RE.search(rest)
    return {
        "name": name,
        "type": rest.split()[0].upper(),
        "not_null": "NOT NULL" in upper or "PRIMARY KEY" in upper,
        "inline_pk": "PRIMARY KEY" in upper,
        "unique": "UNIQUE" in upper,
        "enum": _split_quoted(enum_match.group(1)) if enum_match else [],
    }


def parse_schema(sql_path: str) -> dict:
    """Parse ``sql/schema.sql`` into ``{table: {columns, pk, fks}}``.

    ``columns`` is an ordered list of column dicts; ``pk`` is a list of column
    names; ``fks`` is a list of ``{columns, ref_table, ref_columns}``.
    """

    text = open(sql_path, encoding="utf-8").read()
    body = "\n".join(line.split("--")[0] for line in text.splitlines())

    schema: dict = {}
    for match in _CREATE_TABLE_RE.finditer(body):
        table, block = match.group(1), match.group(2)
        columns: list = []
        pk: list = []
        fks: list = []

        for raw_line in block.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line:
                continue

            fk_match = _FK_RE.search(line)
            if fk_match:
                fks.append(
                    {
                        "columns": _split_ident_list(fk_match.group(1)),
                        "ref_table": fk_match.group(2),
                        "ref_columns": _split_ident_list(fk_match.group(3)),
                    }
                )
                continue

            pk_match = _PK_RE.match(line)
            if pk_match:
                pk = _split_ident_list(pk_match.group(1))
                continue

            if _SKIP_RE.match(line):
                continue

            column = _parse_column(line)
            if column:
                columns.append(column)

        if not pk:
            pk = [column["name"] for column in columns if column["inline_pk"]]
        schema[table] = {"columns": columns, "pk": pk, "fks": fks}
    return schema


# ---------------------------------------------------------------------------
# Schema <-> application consistency
# ---------------------------------------------------------------------------


def check_schema_against_app(schema: dict, table_specs: dict | None = None) -> list:
    """Return a list of human-readable mismatches (empty means consistent)."""

    if table_specs is None:
        from src import crud

        table_specs = crud.TABLE_SPECS

    problems: list = []

    missing = set(table_specs) - set(schema)
    extra = set(schema) - set(table_specs)
    for table in sorted(missing):
        problems.append(f"table {table!r} is used by the app but missing from sql/schema.sql")
    for table in sorted(extra):
        problems.append(f"table {table!r} exists in sql/schema.sql but the app does not know it")

    for table in sorted(set(table_specs) & set(schema)):
        spec = table_specs[table]
        defined = schema[table]
        schema_columns = {column["name"]: column for column in defined["columns"]}

        app_columns = list(spec["columns"])
        if [column["name"] for column in defined["columns"]] != app_columns:
            problems.append(
                f"{table}: column list/order differs between the app and the schema "
                f"(app={app_columns}, schema={[c['name'] for c in defined['columns']]})"
            )

        if defined["pk"] != [spec["primary_key"]]:
            problems.append(
                f"{table}: primary key differs (app={spec['primary_key']!r}, "
                f"schema={defined['pk']!r})"
            )

        schema_fks = {
            tuple(fk["columns"]): (fk["ref_table"], tuple(fk["ref_columns"]))
            for fk in defined["fks"]
        }

        for name, meta in spec["columns"].items():
            column = schema_columns.get(name)
            if column is None:
                continue

            required = bool(meta.get("required"))
            if required != column["not_null"]:
                problems.append(
                    f"{table}.{name}: app required={required} but schema "
                    f"NOT NULL={column['not_null']}"
                )

            options = meta.get("options")
            if options is not None and set(options) != set(column["enum"]):
                problems.append(
                    f"{table}.{name}: enum options differ (app={options}, "
                    f"schema={column['enum']})"
                )

            references = meta.get("references")
            if references:
                expected = (references[0], (references[1],))
                if schema_fks.get((name,)) != expected:
                    problems.append(
                        f"{table}.{name}: app declares FK -> {references} but the schema "
                        f"has {schema_fks.get((name,))}"
                    )

            max_length = meta.get("max")
            varchar = _VARCHAR_RE.match(column["type"])
            if max_length and varchar and int(varchar.group(1)) != int(max_length):
                problems.append(
                    f"{table}.{name}: app max={max_length} but schema type is "
                    f"{column['type']}"
                )

    return problems


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------


def _read_rows(path: str) -> tuple:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return (reader.fieldnames or []), list(reader)


def validate_dataset(data_dir: str, schema: dict, tables=TABLE_ORDER) -> tuple:
    """Validate CSVs in ``data_dir``; return ``(problems, counts, status_totals)``."""

    problems: list = []
    counts: dict = {}
    status_totals: dict = {}
    keys: dict = {}  # table -> set of primary-key tuples
    foreign: dict = {}  # (table, column) -> set of values

    for table in tables:
        path = os.path.join(data_dir, f"{table}.csv")
        if not os.path.exists(path):
            problems.append(f"{table}: missing file {path}")
            continue
        if table not in schema:
            problems.append(f"{table}: not present in sql/schema.sql")
            continue

        expected_columns = [column["name"] for column in schema[table]["columns"]]
        header, rows = _read_rows(path)
        if header != expected_columns:
            problems.append(
                f"{table}: header does not match the schema "
                f"(file={header}, schema={expected_columns})"
            )

        counts[table] = len(rows)
        pk_columns = schema[table]["pk"]
        seen: set = set()

        for line_no, row in enumerate(rows, start=2):
            for column in schema[table]["columns"]:
                name = column["name"]
                value = (row.get(name) or "").strip()
                if column["not_null"] and value == "":
                    problems.append(f"{table}: line {line_no}: required column {name!r} is empty")
                if value and column["enum"] and value not in column["enum"]:
                    problems.append(
                        f"{table}: line {line_no}: {name}={value!r} is not one of {column['enum']}"
                    )
                foreign.setdefault((table, name), set()).add(value)

            if pk_columns:
                key = tuple((row.get(name) or "").strip() for name in pk_columns)
                if all(key):
                    if key in seen:
                        problems.append(f"{table}: line {line_no}: duplicate primary key {key}")
                    seen.add(key)
        keys[table] = seen

        if table == "delivery_attempts":
            for row in rows:
                label = (row.get("status") or "").strip()
                if label:
                    status_totals[label] = status_totals.get(label, 0) + 1

    # Foreign keys (after every table is loaded).
    for table in tables:
        if table not in schema:
            continue
        for fk in schema[table]["fks"]:
            if len(fk["columns"]) != 1 or len(fk["ref_columns"]) != 1:
                continue
            column = fk["columns"][0]
            ref_table = fk["ref_table"]
            ref_column = fk["ref_columns"][0]
            if ref_table not in schema:
                problems.append(f"{table}.{column}: references unknown table {ref_table!r}")
                continue
            valid = {
                (row.get(ref_column) or "").strip()
                for row in (_read_rows(os.path.join(data_dir, f"{ref_table}.csv"))[1]
                            if os.path.exists(os.path.join(data_dir, f"{ref_table}.csv")) else [])
            }
            if not valid:
                problems.append(f"{table}.{column}: cannot verify FK, {ref_table} is empty/missing")
                continue
            for value in foreign.get((table, column), set()):
                if value and value not in valid:
                    problems.append(
                        f"{table}.{column}: value {value!r} has no matching "
                        f"{ref_table}.{ref_column}"
                    )

    return problems, counts, status_totals


# ---------------------------------------------------------------------------
# Bundled synthetic sources vs documented targets
# ---------------------------------------------------------------------------


def verify_source_targets(root: str) -> tuple:
    """Check the bundled synthetic sources against documented target counts."""

    problems: list = []
    report: list = []
    synthetic = os.path.join(root, "data", "synthetic")

    for table in ("drivers", "vehicles", "routes"):
        path = os.path.join(synthetic, f"{table}.csv")
        if not os.path.exists(path):
            problems.append(f"missing bundled source data/synthetic/{table}.csv")
            continue
        _, rows = _read_rows(path)
        target = FULL_DATASET_TARGETS[table]
        report.append(f"{table:<18} {len(rows):>7,} rows (target {target:,})")
        if len(rows) != target:
            problems.append(f"{table}: {len(rows)} rows, expected {target}")

    attempts_path = os.path.join(synthetic, "delivery_attempts.csv")
    if os.path.exists(attempts_path):
        _, rows = _read_rows(synthetic_path := os.path.join(synthetic, "delivery_attempts.csv"))
        report.append(f"{'delivery_attempts':<18} {len(rows):>7,} rows (target {FULL_DATASET_TARGETS['delivery_attempts']:,})")
        if len(rows) != FULL_DATASET_TARGETS["delivery_attempts"]:
            problems.append(
                f"delivery_attempts: {len(rows)} rows, expected "
                f"{FULL_DATASET_TARGETS['delivery_attempts']}"
            )
        totals: dict = {}
        for row in rows:
            label = (row.get("attempt_status") or "").strip().upper()
            totals[label] = totals.get(label, 0) + 1
        for label, expected in SOURCE_STATUS_TARGETS.items():
            actual = totals.get(label, 0)
            report.append(f"  attempt_status={label}: {actual:,} (target {expected:,})")
            if actual != expected:
                problems.append(f"delivery_attempts {label}: {actual} != {expected}")

    report.append(
        "customers/orders: documented targets "
        f"{FULL_DATASET_TARGETS['customers']:,}/{FULL_DATASET_TARGETS['orders']:,} cannot be "
        "verified locally -- the raw Olist dataset is not redistributed (see data/README.md)."
    )
    return problems, report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate the RouteSense schema and data.")
    parser.add_argument("--root", default=REPO_ROOT, help="repository root")
    parser.add_argument("--schema", default=None, help="path to schema.sql")
    parser.add_argument("--data", default=None, help="dataset directory to validate")
    parser.add_argument("--source-targets", action="store_true",
                        help="also check bundled synthetic sources against documented targets")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    schema_path = args.schema or os.path.join(root, "sql", "schema.sql")
    data_dir = args.data or os.path.join(root, "data", "demo")

    failures: list = []

    schema = parse_schema(schema_path)
    print(f"Parsed {len(schema)} tables from {os.path.relpath(schema_path, root)}")
    for table in TABLE_ORDER:
        if table in schema:
            print(f"  {table:<20} {len(schema[table]['columns'])} columns, "
                  f"pk={schema[table]['pk']}, fks={len(schema[table]['fks'])}")

    print("\n[1/3] schema <-> application consistency")
    app_problems = check_schema_against_app(schema)
    failures.extend(app_problems)
    print("  OK" if not app_problems else "\n".join(f"  FAIL: {p}" for p in app_problems))

    print(f"\n[2/3] dataset integrity: {os.path.relpath(data_dir, root)}")
    data_problems, counts, status_totals = validate_dataset(data_dir, schema)
    failures.extend(data_problems)
    for table in TABLE_ORDER:
        if table in counts:
            print(f"  {table:<20} {counts[table]:>7,} rows")
    if status_totals:
        summary = ", ".join(f"{k}={v:,}" for k, v in sorted(status_totals.items()))
        print(f"  delivery status totals: {summary}")
    if data_problems:
        print("\n".join(f"  FAIL: {p}" for p in data_problems))
    else:
        print("  OK")

    print("\n[3/3] bundled synthetic sources vs documented targets")
    if args.source_targets:
        source_problems, report = verify_source_targets(root)
        failures.extend(source_problems)
        for line in report:
            print(f"  {line}")
    else:
        print("  (skipped; pass --source-targets to check)")

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
