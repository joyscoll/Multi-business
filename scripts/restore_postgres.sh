#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${1:?Usage: $0 backup.dump}"
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$DATABASE_URL" "$1"
echo "Restore completed."
