"""Build a small, self-consistent, database-ready *demo* dataset.

Why this exists
---------------
The real RouteSense dataset is derived from the public Olist e-commerce dataset
(plus the synthetic route/driver/vehicle files in ``data/synthetic/``). That
full dataset is **not** redistributed in this repository -- see
``data/README.md`` for provenance, licensing and how to rebuild it. This script
produces a bounded, deterministic, clearly-labelled **synthetic demo** in
``data/demo/`` instead, so a reader can create the schema, load data and run the
application end to end without downloading anything.

Inputs  (committed): data/synthetic/{drivers,vehicles,routes,delivery_attempts}.csv
Outputs (committed): data/demo/{customers,drivers,vehicles,routes,orders,delivery_attempts}.csv

The output column layout matches ``sql/schema.sql`` exactly and is loaded by
``sql/insert.sql`` (foreign-key order: customers, drivers, vehicles, routes,
orders, delivery_attempts).

Determinism
-----------
Every derived value (ids, dates, delays, phone and registration numbers) comes
from a SHA-256 digest of the source keys, so re-running the script always
produces byte-identical files. The data is **synthetic** and must never be
presented as a measurement of real delivery performance.

Usage
-----
    python scripts/build_demo_dataset.py [--orders 300] [--root .]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import os
import sys

#: Brazilian state -> region (public geography, for realistic-looking zones).
STATE_REGION = {
    "AC": "North", "AP": "North", "AM": "North", "PA": "North",
    "RO": "North", "RR": "North", "TO": "North",
    "MA": "Northeast", "PI": "Northeast", "CE": "Northeast", "RN": "Northeast",
    "PB": "Northeast", "PE": "Northeast", "AL": "Northeast", "SE": "Northeast",
    "BA": "Northeast",
    "MT": "Central-West", "MS": "Central-West", "GO": "Central-West",
    "DF": "Central-West",
    "ES": "Southeast", "MG": "Southeast", "RJ": "Southeast", "SP": "Southeast",
    "PR": "South", "SC": "South", "RS": "South",
}

EPOCH = dt.date(2018, 1, 1)
ATTEMPT_EPOCH = dt.datetime(2018, 1, 1, 8, 0, 0)

#: Source attempt labels -> schema ENUM values.
STATUS_MAP = {"SUCCESS": "Delivered", "DELIVERED": "Delivered", "FAILED": "Failed"}

TABLES = ("customers", "drivers", "vehicles", "routes", "orders", "delivery_attempts")


def digest(*parts: object) -> int:
    """Deterministic non-negative integer derived from ``parts``."""

    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str, header: list[str], rows: list[dict]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})
    return len(rows)


def _clean_reason(value: str) -> str:
    reason = (value or "").strip()
    if reason.upper() in ("", "NONE", "NAN"):
        return ""
    return reason[:100]


def build(root: str, n_orders: int) -> dict:
    synth = os.path.join(root, "data", "synthetic")
    demo = os.path.join(root, "data", "demo")

    src_drivers = read_csv(os.path.join(synth, "drivers.csv"))
    src_vehicles = read_csv(os.path.join(synth, "vehicles.csv"))
    src_routes = read_csv(os.path.join(synth, "routes.csv"))
    src_attempts = read_csv(os.path.join(synth, "delivery_attempts.csv"))

    counts: dict = {}

    # --- drivers -------------------------------------------------------------
    drivers = []
    for row in src_drivers:
        did = row["driver_id"]
        drivers.append({
            "driver_id": did,
            "name": row.get("driver_name") or f"Driver {did}",
            "phone": f"55119{digest('phone', did) % 10**8:08d}",
            "license_no": f"BR{digest('lic', did) % 10**8:08d}{did}"[:30],
            "experience_years": int(row.get("experience_years") or 0),
        })
    counts["drivers"] = write_csv(
        os.path.join(demo, "drivers.csv"),
        ["driver_id", "name", "phone", "license_no", "experience_years"],
        drivers,
    )

    # --- vehicles ------------------------------------------------------------
    vehicles = []
    for row in src_vehicles:
        vid = row["vehicle_id"]
        vehicles.append({
            "vehicle_id": vid,
            "vehicle_type": row["vehicle_type"],
            "registration_no": f"REG{digest('reg', vid) % 10**9:09d}",
            "capacity_kg": int(row["capacity_kg"]),
        })
    counts["vehicles"] = write_csv(
        os.path.join(demo, "vehicles.csv"),
        ["vehicle_id", "vehicle_type", "registration_no", "capacity_kg"],
        vehicles,
    )

    # --- routes --------------------------------------------------------------
    routes = []
    for index, row in enumerate(src_routes):
        vehicle = src_vehicles[index % len(src_vehicles)]
        state = (row.get("state") or "SP").upper()[:5]
        routes.append({
            "route_id": row["route_id"],
            "route_name": f"{state} Route",
            "zone": state,
            "origin_hub": "Central Hub",
            "distance_km": row.get("planned_distance_km") or "0",
            "driver_id": vehicle["driver_id"],
            "vehicle_id": vehicle["vehicle_id"],
        })
    counts["routes"] = write_csv(
        os.path.join(demo, "routes.csv"),
        ["route_id", "route_name", "zone", "origin_hub", "distance_km",
         "driver_id", "vehicle_id"],
        routes,
    )

    # --- index the source attempts once --------------------------------------
    attempts_by_order: dict[str, list[dict]] = {}
    for row in src_attempts:
        if row.get("attempt_status") not in STATUS_MAP:
            continue
        attempts_by_order.setdefault(row["order_id"], []).append(row)

    order_keys = sorted(attempts_by_order)[:n_orders]

    # --- customers, orders and attempts --------------------------------------
    customers, orders, attempts_out = [], [], []
    for index, olist_id in enumerate(order_keys, start=1):
        route = routes[digest("route", olist_id) % len(routes)]
        state = route["zone"]
        cust_id = f"CUST{index:05d}"
        order_id = f"ORD{index:05d}"
        seed = digest("ord", olist_id)
        order_date = EPOCH + dt.timedelta(days=seed % 365)

        rows = attempts_by_order[olist_id]
        rows.sort(key=lambda r: int(r.get("attempt_number") or 1))
        delivered = any(STATUS_MAP[r["attempt_status"]] == "Delivered" for r in rows)

        customers.append({
            "customer_id": cust_id,
            "customer_unique_id": f"{digest('uniq', olist_id):032x}",
            "city": f"{state} City",
            "zone": state,
            "region": STATE_REGION.get(state, "Southeast"),
            "pincode": f"{digest('pin', olist_id) % 10**5:05d}",
        })

        orders.append({
            "order_id": order_id,
            "olist_order_id": olist_id,
            "customer_id": cust_id,
            "route_id": route["route_id"],
            "order_date": order_date.isoformat(),
            "promised_date": (order_date + dt.timedelta(days=10)).isoformat(),
            "delivery_date": (order_date + dt.timedelta(days=5)).isoformat() if delivered else "",
            "status": "Delivered" if delivered else "Failed",
            "amount": f"{50 + seed % 500}.{seed % 100:02d}",
            "freight_value": f"{5 + seed % 90}.{(seed // 7) % 100:02d}",
            "zone": state,
        })

        for seq, row in enumerate(rows, start=1):
            status = STATUS_MAP[row["attempt_status"]]
            attempt_time = ATTEMPT_EPOCH + dt.timedelta(
                hours=digest("at", row["attempt_id"]) % 2000,
                minutes=digest("atmin", row["attempt_id"]) % 60,
            )
            attempts_out.append({
                "attempt_id": row["attempt_id"][:10],
                "order_id": order_id,
                "attempt_no": int(row.get("attempt_number") or seq),
                "attempt_time": attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": status,
                "failure_reason": _clean_reason(row.get("issue_reason", "")) if status == "Failed" else "",
                "delay_minutes": "" if status == "Delivered" else str(digest("dly", row["attempt_id"]) % 180),
            })

    counts["customers"] = write_csv(
        os.path.join(demo, "customers.csv"),
        ["customer_id", "customer_unique_id", "city", "zone", "region", "pincode"],
        customers,
    )
    counts["orders"] = write_csv(
        os.path.join(demo, "orders.csv"),
        ["order_id", "olist_order_id", "customer_id", "route_id", "order_date",
         "promised_date", "delivery_date", "status", "amount", "freight_value", "zone"],
        orders,
    )
    counts["delivery_attempts"] = write_csv(
        os.path.join(demo, "delivery_attempts.csv"),
        ["attempt_id", "order_id", "attempt_no", "attempt_time", "status",
         "failure_reason", "delay_minutes"],
        attempts_out,
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RouteSense demo dataset.")
    parser.add_argument("--orders", type=int, default=300,
                        help="number of source orders to include (default: 300)")
    parser.add_argument("--root", default=".",
                        help="repository root (default: current directory)")
    args = parser.parse_args()

    counts = build(os.path.abspath(args.root), args.orders)
    print("Demo dataset written to data/demo/")
    for table in TABLES:
        print(f"  {table:<20} {counts.get(table, 0):>7,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
