-- =====================================================================
-- insert.sql  |  Load the DB-ready CSVs from ``data/demo/``
-- RUN FROM THE PROJECT ROOT (paths below are relative: data/demo/xxx.csv)
-- Requires ``local_infile`` enabled (see README for setup notes).
-- Load order respects foreign keys; foreign-key checks are kept enabled.
-- Trailing ``\r`` is trimmed for cross-platform line endings.
-- =====================================================================
USE delivery_db;

LOAD DATA LOCAL INFILE 'data/demo/customers.csv' INTO TABLE customers
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(customer_id, customer_unique_id, city, zone, region, @pincode)
SET pincode = TRIM(TRAILING '\r' FROM @pincode);

LOAD DATA LOCAL INFILE 'data/demo/drivers.csv' INTO TABLE drivers
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(driver_id, name, phone, license_no, @exp)
SET experience_years = TRIM(TRAILING '\r' FROM @exp);

LOAD DATA LOCAL INFILE 'data/demo/vehicles.csv' INTO TABLE vehicles
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(vehicle_id, vehicle_type, registration_no, @cap)
SET capacity_kg = TRIM(TRAILING '\r' FROM @cap);

LOAD DATA LOCAL INFILE 'data/demo/routes.csv' INTO TABLE routes
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(route_id, route_name, zone, origin_hub, distance_km, driver_id, vehicle_id);

LOAD DATA LOCAL INFILE 'data/demo/orders.csv' INTO TABLE orders
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(order_id, olist_order_id, customer_id, route_id, order_date, promised_date,
 @delivery_date, status, amount, freight_value, zone)
SET delivery_date = NULLIF(TRIM(TRAILING '\r' FROM @delivery_date), '');

LOAD DATA LOCAL INFILE 'data/demo/delivery_attempts.csv' INTO TABLE delivery_attempts
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 LINES
(attempt_id, order_id, attempt_no, attempt_time, status, @reason, @delay)
SET failure_reason = NULLIF(TRIM(TRAILING '\r' FROM @reason), ''),
    delay_minutes  = NULLIF(TRIM(TRAILING '\r' FROM @delay), '');

-- Verify row counts
SELECT 'customers' AS tbl, COUNT(*) AS rows_loaded FROM customers
UNION ALL SELECT 'drivers', COUNT(*) FROM drivers
UNION ALL SELECT 'vehicles', COUNT(*) FROM vehicles
UNION ALL SELECT 'routes', COUNT(*) FROM routes
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'delivery_attempts', COUNT(*) FROM delivery_attempts;