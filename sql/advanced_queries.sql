-- =====================================================================
-- advanced_queries.sql  |  JOINs, GROUP BY, HAVING, aggregations, nested queries
-- NOTE: failure is measured at the ATTEMPT level (delivery_attempts.status),
-- because most failed first attempts are retried and the order ends Delivered.
-- =====================================================================
USE delivery_db;

-- ---------------------------- JOINs ----------------------------------

-- Q1 (INNER JOIN x4): full delivery picture for the first 20 orders
SELECT o.order_id, c.city, o.zone, r.route_name, d.name AS driver,
       v.vehicle_type, o.status, o.amount
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN routes r    ON o.route_id    = r.route_id
JOIN drivers d   ON r.driver_id   = d.driver_id
JOIN vehicles v  ON r.vehicle_id  = v.vehicle_id
ORDER BY o.order_id
LIMIT 20;

-- Q2 (LEFT JOIN): orders with NO delivery attempt yet (Pending / In Transit)
SELECT o.order_id, o.status, o.zone
FROM orders o
LEFT JOIN delivery_attempts da ON o.order_id = da.order_id
WHERE da.attempt_id IS NULL
ORDER BY o.order_id
LIMIT 20;

-- Q3 (JOIN + filter): every failed attempt with its route and driver
SELECT da.attempt_id, da.order_id, da.failure_reason, da.delay_minutes,
       r.route_name, d.name AS driver, d.experience_years
FROM delivery_attempts da
JOIN orders o  ON da.order_id = o.order_id
JOIN routes r  ON o.route_id  = r.route_id
JOIN drivers d ON r.driver_id = d.driver_id
WHERE da.status = 'Failed'
ORDER BY da.delay_minutes DESC
LIMIT 20;

-- ------------------- GROUP BY + aggregations --------------------------

-- Q4: attempt failure rate per zone (hotspot ranking)
SELECT o.zone,
       COUNT(*)                                             AS total_attempts,
       SUM(da.status = 'Failed')                            AS failed_attempts,
       ROUND(100 * SUM(da.status = 'Failed') / COUNT(*), 2) AS failure_rate_pct,
       ROUND(AVG(da.delay_minutes), 1)                      AS avg_delay_min
FROM delivery_attempts da
JOIN orders o ON da.order_id = o.order_id
GROUP BY o.zone
ORDER BY failure_rate_pct DESC;

-- Q5: failure reasons ranked, with average delay
SELECT failure_reason, COUNT(*) AS occurrences,
       ROUND(AVG(delay_minutes), 1) AS avg_delay_min,
       MAX(delay_minutes) AS max_delay_min
FROM delivery_attempts
WHERE status = 'Failed'
GROUP BY failure_reason
ORDER BY occurrences DESC;

-- Q6: failures by hour of day (time hotspots)
SELECT HOUR(attempt_time) AS hour_of_day,
       COUNT(*) AS attempts,
       SUM(status = 'Failed') AS failed,
       ROUND(100 * SUM(status = 'Failed') / COUNT(*), 2) AS failure_rate_pct
FROM delivery_attempts
GROUP BY HOUR(attempt_time)
ORDER BY hour_of_day;

-- Q7: route performance (failure rate, average delay, driver experience)
SELECT r.route_id, r.route_name, d.name AS driver, d.experience_years,
       COUNT(*) AS attempts,
       ROUND(100 * SUM(da.status = 'Failed') / COUNT(*), 2) AS failure_rate_pct,
       ROUND(AVG(da.delay_minutes), 1) AS avg_delay_min
FROM routes r
JOIN drivers d ON r.driver_id = d.driver_id
JOIN orders o ON o.route_id = r.route_id
JOIN delivery_attempts da ON da.order_id = o.order_id
GROUP BY r.route_id, r.route_name, d.name, d.experience_years
ORDER BY failure_rate_pct DESC;

-- Q8: monthly order volume and revenue
SELECT DATE_FORMAT(order_date, '%Y-%m') AS month,
       COUNT(*) AS orders, ROUND(SUM(amount), 2) AS revenue
FROM orders
GROUP BY DATE_FORMAT(order_date, '%Y-%m')
ORDER BY month;

-- ------------------------------ HAVING --------------------------------

-- Q9: zones with more than 20% attempt failure and at least 50 attempts
SELECT o.zone, COUNT(*) AS attempts,
       ROUND(100 * SUM(da.status = 'Failed') / COUNT(*), 2) AS failure_rate_pct
FROM delivery_attempts da
JOIN orders o ON da.order_id = o.order_id
GROUP BY o.zone
HAVING COUNT(*) >= 50 AND failure_rate_pct > 20
ORDER BY failure_rate_pct DESC;

-- Q10: drivers with 30+ attempts and average delay above 60 minutes
SELECT d.driver_id, d.name, COUNT(*) AS attempts,
       ROUND(AVG(da.delay_minutes), 1) AS avg_delay_min
FROM drivers d
JOIN routes r ON r.driver_id = d.driver_id
JOIN orders o ON o.route_id = r.route_id
JOIN delivery_attempts da ON da.order_id = o.order_id
GROUP BY d.driver_id, d.name
HAVING COUNT(*) >= 30 AND AVG(da.delay_minutes) > 60;

-- --------------------------- NESTED QUERIES ---------------------------

-- Q11 (subquery in HAVING): zones failing MORE than the overall failure rate
SELECT o.zone,
       ROUND(100 * SUM(da.status = 'Failed') / COUNT(*), 2) AS zone_rate_pct,
       (SELECT ROUND(100 * SUM(status = 'Failed') / COUNT(*), 2)
        FROM delivery_attempts) AS overall_rate_pct
FROM delivery_attempts da
JOIN orders o ON da.order_id = o.order_id
GROUP BY o.zone
HAVING zone_rate_pct > (SELECT 100 * SUM(status = 'Failed') / COUNT(*)
                        FROM delivery_attempts)
ORDER BY zone_rate_pct DESC;

-- Q12 (IN subquery): orders that needed more than one attempt
SELECT o.order_id, o.zone, o.status
FROM orders o
WHERE o.order_id IN (SELECT order_id FROM delivery_attempts
                     GROUP BY order_id HAVING COUNT(*) > 1)
ORDER BY o.order_id
LIMIT 20;

-- Q13 (nested + aggregate subquery): drivers whose average delay is above the overall average
SELECT d.driver_id, d.name, d.experience_years
FROM drivers d
WHERE d.driver_id IN (
    SELECT r.driver_id
    FROM routes r
    JOIN orders o ON o.route_id = r.route_id
    JOIN delivery_attempts da ON da.order_id = o.order_id
    GROUP BY r.driver_id
    HAVING AVG(da.delay_minutes) > (SELECT AVG(delay_minutes) FROM delivery_attempts));

-- Q14 (derived table): dominant failure reason per zone
SELECT t.zone, t.failure_reason, t.cnt
FROM (SELECT o.zone, da.failure_reason, COUNT(*) AS cnt
      FROM delivery_attempts da JOIN orders o ON da.order_id = o.order_id
      WHERE da.status = 'Failed'
      GROUP BY o.zone, da.failure_reason) t
WHERE t.cnt = (SELECT MAX(cnt2) FROM
               (SELECT o.zone AS z, COUNT(*) AS cnt2
                FROM delivery_attempts da JOIN orders o ON da.order_id = o.order_id
                WHERE da.status = 'Failed'
                GROUP BY o.zone, da.failure_reason) m
               WHERE m.z = t.zone)
ORDER BY t.cnt DESC;

-- Q15 (correlated subquery): orders delivered later than promised
SELECT o.order_id, o.zone, o.promised_date, o.delivery_date,
       DATEDIFF(o.delivery_date, o.promised_date) AS days_late
FROM orders o
WHERE o.delivery_date > o.promised_date
  AND o.status = 'Delivered'
ORDER BY days_late DESC
LIMIT 20;