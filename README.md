# Daily Merchant Risk Reporting — Interview Kit (Option 2)

## Overview

Welcome!  
This exercise is designed to assess your hands-on data engineering skills in building reliable from-raw pipelines, handling messy real-world data, and ensuring correctness and quality.

### Deliverables
You are expected to deliver:
1. A data pipeline that reads sample CSVs and produces a **daily merchant risk report**.
2. A strategy for handling edge cases (duplicates, out-of-order events, partial captures, disputes after captures, fraud signals).
3. Documentation of assumptions, quality checks, and idempotency behavior.

---

## What We Provide

You are given:

### 1) Schema (in `ddl/schema.sql`)
Defines the tables for:
- payment_events
- checkout_payments
- audit_logs
- merchant_daily_risk_reports

### 2) Base data (in `data/`)
Three base CSVs:
- payment_events_base.csv  
- checkout_payments_base.csv  
- audit_logs_base.csv  

These cover only the *happy path* (simple authorized → captured → fraud signal).

### 3) Starter edge case CSVs
Candidate must merge and expand on these:
- duplicates_starter.csv
- partial_captures_starter.csv
- out_of_order_starter.csv
- fraud_signals_starter.csv

---

## Your Task

### Step 0 — Start Postgres
Make sure you have Docker installed, then from the project root directory run:

```shell
docker-compose up -d
```

This starts a Postgres 16 instance on `localhost:5432` with user `postgres` / password `postgres`.

Set the connection environment variables so that `psql` and the load script can connect:

```shell
export PGHOST=localhost
export PGUSER=postgres
export PGPASSWORD=postgres
export PGDATABASE=postgres
```

### Step 1 — Create the tables
Run the schema in Postgres:

```shell
psql -f ddl/schema.sql
```

### Step 2 — Load base CSVs
From the **project root directory**, run the provided load script:

```shell
bash ddl/load_data.sh
```

> **Note:** The load script uses relative paths (`data/...`), so it must be run from the project root.

### Step 3 — Build the pipeline
Your pipeline should produce a table `merchant_daily_risk_reports` with columns:

| metric | description |
|--------|-------------|
| merchant_id | merchant identifier |
| report_date | date of the report |
| total_authorized_amount | sum of authorizations |
| total_captured_amount | sum of captures |
| total_refunded_amount | sum of refunds |
| dispute_count | count of disputes |
| fraud_signal_count | count of fraud records |

The pipeline should handle:
- duplicates
- out-of-order events
- partial captures
- disputes that occur before, during, or after payment lifecycle
- fraud signals counted independently

### Step 4 — Add more tests
Add your own test data (additional CSVs or SQL inserts) to validate your pipeline.

### Step 5 — Documentation
In a `README_RESULTS.md`, explain:
- your assumptions
- quality checks and invariants
- idempotency behavior
- how your pipeline handles edge cases

---

## Evaluation Criteria

We are assessing:
✔ Correct metric computation  
✔ Handling of real-world issues  
✔ Idempotency  
✔ Scalability & clarity  
✔ Documentation & explanation  
✔ Quality checks and validation

---

## Recommended Tools

You may implement this using your preferred stack, e.g.:
- Python (Pandas / SQLAlchemy / Postgres)
- SQL + dbt
- Scala / Spark
- TypeScript
- Any tooling that can load CSV → Postgres → transform

Be prepared to explain your choices.

Good luck!