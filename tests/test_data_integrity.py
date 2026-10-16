"""Tests for the schema/data validator (scripts/validate_data.py)."""

import os
import tempfile

from scripts import validate_data


def _make_tmp_csv(tmpdir, name, header, rows):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        import csv

        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def test_schema_against_app_consistent():
    schema = validate_data.parse_schema("sql/schema.sql")
    problems = validate_data.check_schema_against_app(schema)
    assert not problems, f"schema/app mismatch: {problems}"


def test_demo_data_validates_cleanly():
    schema = validate_data.parse_schema("sql/schema.sql")
    problems, counts, status = validate_data.validate_dataset("data/demo", schema)
    assert not problems, f"demo dataset invalid: {problems}"
    assert counts["customers"] == 300
    assert counts["orders"] == 300
    assert counts["drivers"] == 250
    assert counts["vehicles"] == 250
    assert counts["routes"] == 270
    assert "Delivered" in status and "Failed" in status


def test_duplicate_primary_key_detected():
    schema = validate_data.parse_schema("sql/schema.sql")
    tmp = tempfile.mkdtemp()
    try:
        # customers: CUST00001 appears twice
        customers = [
            {
                "customer_id": "CUST00001",
                "customer_unique_id": "a"*32,
                "city": "SP City",
                "zone": "SP",
                "region": "Southeast",
                "pincode": "01000",
            },
            {
                "customer_id": "CUST00001",
                "customer_unique_id": "b"*32,
                "city": "RJ City",
                "zone": "RJ",
                "region": "Southeast",
                "pincode": "20000",
            },
        ]
        _make_tmp_csv(tmp, "customers.csv", list(customers[0]), customers)
        # other tables minimal
        _make_tmp_csv(tmp, "drivers.csv", ["driver_id","name","phone","license_no","experience_years"], [
            {"driver_id":"D0001","name":"D1","phone":"5511900000000","license_no":"BR00000000D0001","experience_years":"2"},
        ])
        _make_tmp_csv(tmp, "vehicles.csv", ["vehicle_id","vehicle_type","registration_no","capacity_kg"], [
            {"vehicle_id":"V0001","vehicle_type":"VAN","registration_no":"REG0000001","capacity_kg":"100"},
        ])
        _make_tmp_csv(tmp, "routes.csv", ["route_id","route_name","zone","origin_hub","distance_km","driver_id","vehicle_id"], [
            {"route_id":"R0001","route_name":"SP Route","zone":"SP","origin_hub":"Hub","distance_km":"10","driver_id":"D0001","vehicle_id":"V0001"},
        ])
        _make_tmp_csv(tmp, "orders.csv", ["order_id","olist_order_id","customer_id","route_id","order_date","promised_date","delivery_date","status","amount","freight_value","zone"], [
            {"order_id":"ORD00001","olist_order_id":"o1","customer_id":"CUST00001","route_id":"R0001","order_date":"2018-01-01","promised_date":"2018-01-11","delivery_date":"","status":"Failed","amount":"10.00","freight_value":"5.00","zone":"SP"},
        ])
        _make_tmp_csv(tmp, "delivery_attempts.csv", ["attempt_id","order_id","attempt_no","attempt_time","status","failure_reason","delay_minutes"], [
            {"attempt_id":"A0000001","order_id":"ORD00001","attempt_no":"1","attempt_time":"2018-01-02 08:00:00","status":"Failed","failure_reason":"Issue","delay_minutes":"10"},
        ])
        problems, _, _ = validate_data.validate_dataset(tmp, schema)
        assert any("duplicate primary key" in p for p in problems)
    finally:
        import shutil

        shutil.rmtree(tmp)


def test_broken_foreign_key_detected():
    schema = validate_data.parse_schema("sql/schema.sql")
    tmp = tempfile.mkdtemp()
    try:
        _make_tmp_csv(tmp, "customers.csv", ["customer_id","customer_unique_id","city","zone","region","pincode"], [
            {"customer_id":"CUST00001","customer_unique_id":"a"*32,"city":"SP City","zone":"SP","region":"Southeast","pincode":"01000"},
        ])
        _make_tmp_csv(tmp, "drivers.csv", ["driver_id","name","phone","license_no","experience_years"], [
            {"driver_id":"D0001","name":"D1","phone":"5511900000000","license_no":"BR00000000D0001","experience_years":"2"},
        ])
        _make_tmp_csv(tmp, "vehicles.csv", ["vehicle_id","vehicle_type","registration_no","capacity_kg"], [
            {"vehicle_id":"V0001","vehicle_type":"VAN","registration_no":"REG0000001","capacity_kg":"100"},
        ])
        _make_tmp_csv(tmp, "routes.csv", ["route_id","route_name","zone","origin_hub","distance_km","driver_id","vehicle_id"], [
            {"route_id":"R0001","route_name":"SP Route","zone":"SP","origin_hub":"Hub","distance_km":"10","driver_id":"D0001","vehicle_id":"V0001"},
        ])
        _make_tmp_csv(tmp, "orders.csv", ["order_id","olist_order_id","customer_id","route_id","order_date","promised_date","delivery_date","status","amount","freight_value","zone"], [
            {"order_id":"ORD00001","olist_order_id":"o1","customer_id":"CUST00001","route_id":"R0002","order_date":"2018-01-01","promised_date":"2018-01-11","delivery_date":"","status":"Failed","amount":"10.00","freight_value":"5.00","zone":"SP"},
        ])
        _make_tmp_csv(tmp, "delivery_attempts.csv", ["attempt_id","order_id","attempt_no","attempt_time","status","failure_reason","delay_minutes"], [
            {"attempt_id":"A0000001","order_id":"ORD00001","attempt_no":"1","attempt_time":"2018-01-02 08:00:00","status":"Failed","failure_reason":"Issue","delay_minutes":"10"},
        ])
        problems, _, _ = validate_data.validate_dataset(tmp, schema)
        assert any("has no matching routes.route_id" in p for p in problems)
    finally:
        import shutil

        shutil.rmtree(tmp)


def test_missing_required_column_detected():
    schema = validate_data.parse_schema("sql/schema.sql")
    tmp = tempfile.mkdtemp()
    try:
        _make_tmp_csv(tmp, "customers.csv", ["customer_id","customer_unique_id","city","zone","region","pincode"], [
            {"customer_id":"CUST00001","customer_unique_id":"","city":"SP City","zone":"SP","region":"Southeast","pincode":"01000"},
        ])
        _make_tmp_csv(tmp, "drivers.csv", ["driver_id","name","phone","license_no","experience_years"], [
            {"driver_id":"D0001","name":"D1","phone":"5511900000000","license_no":"BR00000000D0001","experience_years":"2"},
        ])
        _make_tmp_csv(tmp, "vehicles.csv", ["vehicle_id","vehicle_type","registration_no","capacity_kg"], [
            {"vehicle_id":"V0001","vehicle_type":"VAN","registration_no":"REG0000001","capacity_kg":"100"},
        ])
        _make_tmp_csv(tmp, "routes.csv", ["route_id","route_name","zone","origin_hub","distance_km","driver_id","vehicle_id"], [
            {"route_id":"R0001","route_name":"SP Route","zone":"SP","origin_hub":"Hub","distance_km":"10","driver_id":"D0001","vehicle_id":"V0001"},
        ])
        _make_tmp_csv(tmp, "orders.csv", ["order_id","olist_order_id","customer_id","route_id","order_date","promised_date","delivery_date","status","amount","freight_value","zone"], [
            {"order_id":"ORD00001","olist_order_id":"o1","customer_id":"CUST00001","route_id":"R0001","order_date":"2018-01-01","promised_date":"2018-01-11","delivery_date":"","status":"Failed","amount":"10.00","freight_value":"5.00","zone":"SP"},
        ])
        _make_tmp_csv(tmp, "delivery_attempts.csv", ["attempt_id","order_id","attempt_no","attempt_time","status","failure_reason","delay_minutes"], [
            {"attempt_id":"A0000001","order_id":"ORD00001","attempt_no":"1","attempt_time":"2018-01-02 08:00:00","status":"Failed","failure_reason":"Issue","delay_minutes":"10"},
        ])
        problems, _, _ = validate_data.validate_dataset(tmp, schema)
        assert any("required column 'customer_unique_id'" in p for p in problems)
    finally:
        import shutil

        shutil.rmtree(tmp)
