#!/usr/bin/env bash
# Wipes all Delta Lake tables under DELTA_PATH so the pipeline can be
# re-run from scratch against the current Postgres source data.
#
# Only directories containing a _delta_log/ subdirectory are deleted —
# the canonical Delta table marker. Non-Delta content is left untouched.
# Does NOT touch Postgres — source data is preserved.
# Must be run from the project root (same requirement as the datajobs).

set -euo pipefail

LAYER_DIR="${DELTA_PATH:-./datalake/layer}"

echo "Scanning for Delta tables in: $(realpath "$LAYER_DIR")"

found=0
while IFS= read -r -d '' log_dir; do
    table_dir="$(dirname "$log_dir")"
    echo "  ✓ Wiped $(realpath "$table_dir")"
    rm -rf "$table_dir"
    found=$((found + 1))
done < <(find "$LAYER_DIR" -type d -name "_delta_log" -print0 2>/dev/null)

if [ "$found" -eq 0 ]; then
    echo "  – No Delta tables found (nothing to reset)"
else
    echo "$found Delta table(s) removed."
fi

echo "Re-run the pipeline to repopulate:"
echo "  venv/bin/python -m accrue.datajobs.bronze"
echo "  venv/bin/python -m accrue.datajobs.silver"
echo "  venv/bin/python -m accrue.datajobs.gold"
