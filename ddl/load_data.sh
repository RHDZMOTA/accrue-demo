#!/usr/bin/env bash

# Assumes psql env variables are set
# e.g.
# export PGHOST=localhost
# export PGUSER=postgres
# export PGPASSWORD=postgres
# export PGDATABASE=postgres

echo "Loading base CSV data..."

psql <<EOF
\copy payment_events FROM 'data/payment_events_base.csv' CSV HEADER;
\copy checkout_payments FROM 'data/checkout_payments_base.csv' CSV HEADER;
\copy audit_logs FROM 'data/audit_logs_base.csv' CSV HEADER;
EOF

echo "Base data loaded."