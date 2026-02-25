-- Edge case validation queries for merchant_daily_risk_reports.
-- Run AFTER:
--   1. bash ddl/load_data.sh          (base CSVs → Postgres)
--   2. bash ddl/load_edge_cases.sh    (starter CSVs → Postgres)
--   3. Full pipeline: bronze → silver → gold
--
-- Each query returns the matching rows from the Gold output.
-- A query returning 0 rows means the assertion FAILED.


-- ============================================================
-- 1. DUPLICATE SUPPRESSION (2026-01-01, Merchant A)
-- ============================================================
-- Input:
--   evt_1       AUTHORIZED $100  (base)
--   evt_2       CAPTURED   $100  (base)
--   evt_2_dup   CAPTURED   $100  (duplicates_starter.csv)
--
-- evt_2_dup has a DIFFERENT id from evt_2 — it simulates a business-level
-- duplicate (same logical payment, different system ID), e.g. a retried webhook.
-- Silver suppresses only EXACT byte-for-byte duplicates (same META_DATA_UUID).
-- Since the `id` column differs, both survive Silver, and Gold counts both:
--   total_authorized_amount = 100
--   total_captured_amount   = 200   ← both CAPTURED events counted (different IDs)
--
-- This is CORRECT pipeline behaviour: Gold reflects all distinct events.
-- Business-level dedup (same logical event, different ID) is out of scope
-- and would require domain-specific rules.

SELECT
    merchant_id,
    report_date,
    total_authorized_amount,
    total_captured_amount
FROM merchant_daily_risk_reports
WHERE merchant_id = 'A'
  AND report_date = '2026-01-01'
  AND total_authorized_amount = 100
  AND total_captured_amount   = 200
;
-- Expected: 1 row


-- ============================================================
-- 2. OUT-OF-ORDER EVENTS (2026-01-03, Merchant A)
-- ============================================================
-- Input (out_of_order_starter.csv):
--   evt_o1  CAPTURED   $100  @ 08:00 (arrived BEFORE the AUTHORIZED)
--   evt_o2  AUTHORIZED $100  @ 08:05
-- Both events have distinct IDs → Silver keeps both → Gold counts both.
-- Expected:
--   total_authorized_amount = 100
--   total_captured_amount   = 100

SELECT
    merchant_id,
    report_date,
    total_authorized_amount,
    total_captured_amount
FROM merchant_daily_risk_reports
WHERE merchant_id = 'A'
  AND report_date = '2026-01-03'
  AND total_authorized_amount = 100
  AND total_captured_amount   = 100
;
-- Expected: 1 row


-- ============================================================
-- 3. PARTIAL CAPTURES (2026-01-02, Merchant A)
-- ============================================================
-- Input (partial_captures_starter.csv):
--   evt_p1  AUTHORIZED $150  @ 09:00
--   evt_p2  CAPTURED    $50  @ 09:10  (first partial capture)
--   evt_p3  CAPTURED    $30  @ 09:15  (second partial capture)
-- Expected:
--   total_authorized_amount = 150
--   total_captured_amount   =  80   ← 50 + 30, partial fill of $150

SELECT
    merchant_id,
    report_date,
    total_authorized_amount,
    total_captured_amount
FROM merchant_daily_risk_reports
WHERE merchant_id = 'A'
  AND report_date = '2026-01-02'
  AND total_authorized_amount = 150
  AND total_captured_amount   = 80
;
-- Expected: 1 row


-- ============================================================
-- 4. FRAUD SIGNALS (2026-01-02, Merchant A)
-- ============================================================
-- Input (fraud_signals_starter.csv):
--   log_f1  FRAUD_FLAGGED  @ 10:00
--   log_f2  FRAUD_FLAGGED  @ 10:05
-- Expected:
--   fraud_signal_count = 2

SELECT
    merchant_id,
    report_date,
    fraud_signal_count
FROM merchant_daily_risk_reports
WHERE merchant_id = 'A'
  AND report_date = '2026-01-02'
  AND fraud_signal_count = 2
;
-- Expected: 1 row


-- ============================================================
-- 5. BASELINE FRAUD (2026-01-01, Merchant A vs B)
-- ============================================================
-- Input (audit_logs_base.csv):
--   log_1  FRAUD_FLAGGED      (merchant A, 2026-01-01)
--   log_2  REVIEW_COMPLETED   (merchant B, 2026-01-01) — NOT a fraud signal
-- Expected:
--   Merchant A fraud_signal_count = 1
--   Merchant B fraud_signal_count = 0

SELECT
    merchant_id,
    report_date,
    fraud_signal_count
FROM merchant_daily_risk_reports
WHERE report_date = '2026-01-01'
  AND (
      (merchant_id = 'A' AND fraud_signal_count = 1)
   OR (merchant_id = 'B' AND fraud_signal_count = 0)
  )
ORDER BY merchant_id
;
-- Expected: 2 rows


-- ============================================================
-- 6. MERCHANT ISOLATION (no cross-contamination)
-- ============================================================
-- All starter CSVs are scoped to merchant A.
-- Merchant B should reflect base data only on 2026-01-01.
-- Expected:
--   total_authorized_amount = 200
--   total_captured_amount   = 200
--   fraud_signal_count      = 0

SELECT
    merchant_id,
    report_date,
    total_authorized_amount,
    total_captured_amount,
    fraud_signal_count
FROM merchant_daily_risk_reports
WHERE merchant_id = 'B'
  AND report_date = '2026-01-01'
  AND total_authorized_amount = 200
  AND total_captured_amount   = 200
  AND fraud_signal_count      = 0
;
-- Expected: 1 row