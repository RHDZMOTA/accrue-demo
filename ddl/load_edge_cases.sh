#!/usr/bin/env bash

# Loads starter edge-case records on top of the base data.
# Run AFTER ddl/load_data.sh.
#
# Assumes psql env variables are set, e.g.:
#   export PGHOST=localhost
#   export PGUSER=postgres
#   export PGPASSWORD=postgres
#   export PGDATABASE=postgres
#
# Must be run from the project root directory (csv paths are relative).

set -euo pipefail

echo "Loading edge-case starter data..."

psql <<EOF
-- Duplicates: a repeat of evt_2 (CAPTURED) to test deduplication logic.
\copy payment_events FROM 'data/duplicates_starter.csv' CSV HEADER;

-- Out-of-order: CAPTURED (evt_o1) arrives before AUTHORIZED (evt_o2).
\copy payment_events FROM 'data/out_of_order_starter.csv' CSV HEADER;

-- Partial captures: one AUTHORIZED + one CAPTURED, with a second CAPTURED
-- to follow (evt_p3 is not in the starter file — covered in unit tests).
\copy payment_events FROM 'data/partial_captures_starter.csv' CSV HEADER;

-- Fraud signals: two FRAUD_FLAGGED audit log entries for merchant A.
\copy audit_logs FROM 'data/fraud_signals_starter.csv' CSV HEADER;
EOF

echo "Edge-case data loaded."
