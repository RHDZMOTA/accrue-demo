-- Candidate can use this to validate base case

SELECT
  merchant_id,
  SUM(CASE WHEN event_type = 'AUTHORIZED' THEN amount ELSE 0 END) AS total_authorized_amount,
  SUM(CASE WHEN event_type = 'CAPTURED' THEN amount ELSE 0 END) AS total_captured_amount
FROM payment_events
GROUP BY merchant_id;