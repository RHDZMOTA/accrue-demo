-- Base tables
CREATE TABLE payment_events (
  id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE checkout_payments (
  id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  amount NUMERIC NOT NULL,
  captured_amount NUMERIC NOT NULL,
  refund_amount NUMERIC DEFAULT 0,
  dispute_status TEXT DEFAULT '',
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE audit_logs (
  id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  action TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL
);

-- Reporting table
CREATE TABLE merchant_daily_risk_reports (
  merchant_id TEXT NOT NULL,
  report_date DATE NOT NULL,
  total_authorized_amount NUMERIC DEFAULT 0,
  total_captured_amount NUMERIC DEFAULT 0,
  total_refunded_amount NUMERIC DEFAULT 0,
  dispute_count INT DEFAULT 0,
  fraud_signal_count INT DEFAULT 0,
  PRIMARY KEY (merchant_id, report_date)
);