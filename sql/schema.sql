-- =====================================================================
-- schema.sql  |  Delivery Failure Analytics  |  Member 1
-- Creates database delivery_db with 6 tables, PK/FK constraints, indexes.
-- Run FIRST, then insert.sql, advanced_queries.sql, procedures.sql.
--
-- NON-DESTRUCTIVE: this script never drops a database or a table, and it is
-- safe to run more than once. To intentionally wipe and recreate everything
-- during development, run sql/reset_database.sql instead (and read its
-- warnings first).
-- =====================================================================
CREATE DATABASE IF NOT EXISTS delivery_db CHARACTER SET utf8mb4;
USE delivery_db;

CREATE TABLE IF NOT EXISTS customers (
    customer_id        VARCHAR(10) PRIMARY KEY,
    customer_unique_id VARCHAR(40) NOT NULL,
    city               VARCHAR(80),
    zone               VARCHAR(5)  NOT NULL,   -- Brazilian state code (SP, RJ ...)
    region             VARCHAR(20),
    pincode            VARCHAR(10)
);

CREATE TABLE IF NOT EXISTS drivers (
    driver_id        VARCHAR(10) PRIMARY KEY,
    name             VARCHAR(100) NOT NULL,
    phone            VARCHAR(20),
    license_no       VARCHAR(30) UNIQUE,
    experience_years INT CHECK (experience_years >= 0)
);

CREATE TABLE IF NOT EXISTS vehicles (
    vehicle_id      VARCHAR(10) PRIMARY KEY,
    vehicle_type    VARCHAR(30) NOT NULL,
    registration_no VARCHAR(20) UNIQUE,
    capacity_kg     INT CHECK (capacity_kg > 0)
);

CREATE TABLE IF NOT EXISTS routes (
    route_id    VARCHAR(10) PRIMARY KEY,
    route_name  VARCHAR(100) NOT NULL,
    zone        VARCHAR(5) NOT NULL,
    origin_hub  VARCHAR(100),
    distance_km DECIMAL(7,2),
    driver_id   VARCHAR(10) NOT NULL,
    vehicle_id  VARCHAR(10) NOT NULL,
    CONSTRAINT fk_routes_driver  FOREIGN KEY (driver_id)  REFERENCES drivers(driver_id),
    CONSTRAINT fk_routes_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id       VARCHAR(10) PRIMARY KEY,
    olist_order_id VARCHAR(40),
    customer_id    VARCHAR(10) NOT NULL,
    route_id       VARCHAR(10) NOT NULL,
    order_date     DATE NOT NULL,
    promised_date  DATE,
    delivery_date  DATE,                        -- NULL if not delivered
    status         ENUM('Delivered','Failed','Pending','In Transit') NOT NULL,
    amount         DECIMAL(10,2),
    freight_value  DECIMAL(10,2),
    zone           VARCHAR(5) NOT NULL,
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    CONSTRAINT fk_orders_route    FOREIGN KEY (route_id)    REFERENCES routes(route_id)
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id     VARCHAR(10) PRIMARY KEY,
    order_id       VARCHAR(10) NOT NULL,
    attempt_no     INT NOT NULL,
    attempt_time   DATETIME NOT NULL,
    status         ENUM('Delivered','Failed') NOT NULL,
    failure_reason VARCHAR(100),                -- NULL when delivered
    delay_minutes  INT DEFAULT 0,
    CONSTRAINT fk_attempts_order FOREIGN KEY (order_id) REFERENCES orders(order_id),
    CONSTRAINT uq_order_attempt UNIQUE (order_id, attempt_no)
);

-- NOTE: MySQL has no CREATE INDEX IF NOT EXISTS. The statements below
-- succeed on a fresh database (the normal case). Re-running them against
-- an existing schema reports harmless "Duplicate key name" errors; use
-- sql/reset_database.sql for a clean rebuild.
CREATE INDEX idx_orders_zone     ON orders(zone);
CREATE INDEX idx_orders_route    ON orders(route_id);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_attempts_order  ON delivery_attempts(order_id);
CREATE INDEX idx_attempts_status ON delivery_attempts(status);