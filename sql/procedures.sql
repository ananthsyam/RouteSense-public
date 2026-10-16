-- =====================================================================
-- procedures.sql  |  Stored procedures (Member 3 can CALL these from Python)
-- Run in MySQL Workbench or terminal if PyCharm's runner mishandles DELIMITER.
-- =====================================================================
USE delivery_db;

DROP PROCEDURE IF EXISTS GetZoneFailureReport;
DROP PROCEDURE IF EXISTS GetRoutePerformance;

DELIMITER //

-- Failure report for one zone, compared with the overall rate
CREATE PROCEDURE GetZoneFailureReport(IN p_zone VARCHAR(5))
BEGIN
    DECLARE overall_rate DECIMAL(6,2);

    IF NOT EXISTS (SELECT 1 FROM orders WHERE zone = p_zone) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Zone not found';
    END IF;

    SELECT ROUND(100 * SUM(status = 'Failed') / COUNT(*), 2)
      INTO overall_rate FROM delivery_attempts;

    SELECT o.zone,
           COUNT(DISTINCT o.order_id)                            AS total_orders,
           COUNT(da.attempt_id)                                  AS total_attempts,
           SUM(da.status = 'Failed')                             AS failed_attempts,
           ROUND(100 * SUM(da.status = 'Failed') / COUNT(da.attempt_id), 2) AS zone_failure_rate_pct,
           overall_rate                                          AS overall_failure_rate_pct,
           ROUND(AVG(da.delay_minutes), 1)                       AS avg_delay_min
    FROM orders o
    LEFT JOIN delivery_attempts da ON o.order_id = da.order_id
    WHERE o.zone = p_zone
    GROUP BY o.zone;
END //

-- Performance summary for one route
CREATE PROCEDURE GetRoutePerformance(IN p_route_id VARCHAR(10))
BEGIN
    IF NOT EXISTS (SELECT 1 FROM routes WHERE route_id = p_route_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Route not found';
    END IF;

    SELECT r.route_id, r.route_name, d.name AS driver, d.experience_years,
           COUNT(da.attempt_id)                                   AS total_attempts,
           SUM(da.status = 'Failed')                              AS failed_attempts,
           ROUND(100 * SUM(da.status = 'Failed') / COUNT(da.attempt_id), 2) AS failure_rate_pct,
           ROUND(AVG(da.delay_minutes), 1)                        AS avg_delay_min,
           (SELECT da2.failure_reason
              FROM delivery_attempts da2
              JOIN orders o2 ON da2.order_id = o2.order_id
             WHERE o2.route_id = r.route_id AND da2.status = 'Failed'
             GROUP BY da2.failure_reason
             ORDER BY COUNT(*) DESC LIMIT 1)                      AS dominant_failure_reason
    FROM routes r
    JOIN drivers d ON r.driver_id = d.driver_id
    LEFT JOIN orders o ON o.route_id = r.route_id
    LEFT JOIN delivery_attempts da ON da.order_id = o.order_id
    WHERE r.route_id = p_route_id
    GROUP BY r.route_id, r.route_name, d.name, d.experience_years;
END //

DELIMITER ;

-- Test calls
CALL GetZoneFailureReport('RJ');
CALL GetRoutePerformance('RT001');