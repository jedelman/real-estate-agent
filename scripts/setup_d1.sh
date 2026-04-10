#!/usr/bin/env bash
# Setup Cloudflare D1 for real-estate-agent
# Usage: CF_API_TOKEN=xxx CF_ACCOUNT_ID=xxx bash scripts/setup_d1.sh
set -euo pipefail

DB_NAME="real-estate-agent"
MIGRATIONS_DIR="$(dirname "$0")/../db/migrations"

: "${CF_API_TOKEN:?CF_API_TOKEN must be set}"
: "${CF_ACCOUNT_ID:?CF_ACCOUNT_ID must be set}"

BASE="https://api.cloudflare.com/client/v4/accounts/${CF_ACCOUNT_ID}/d1/database"

_cf() {
  curl -sf -H "Authorization: Bearer ${CF_API_TOKEN}" \
       -H "Content-Type: application/json" \
       "$@"
}

# ---------------------------------------------------------------------------
# 1. Create database (no-op if it already exists)
# ---------------------------------------------------------------------------
echo "→ Looking for existing database '${DB_NAME}'..."
EXISTING=$(
  _cf "${BASE}" |
  python3 -c "
import sys, json
data = json.load(sys.stdin)
dbs = data.get('result', [])
match = next((d for d in dbs if d['name'] == '${DB_NAME}'), None)
print(match['uuid'] if match else '')
"
)

if [ -n "$EXISTING" ]; then
  DB_ID="$EXISTING"
  echo "  ✓ Found existing database: ${DB_ID}"
else
  echo "  + Creating database '${DB_NAME}'..."
  RESP=$(_cf -X POST "${BASE}" -d "{\"name\":\"${DB_NAME}\"}")
  DB_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['uuid'])")
  echo "  ✓ Created: ${DB_ID}"
fi

# ---------------------------------------------------------------------------
# 2. Apply each migration in order
# ---------------------------------------------------------------------------
echo "→ Applying migrations from ${MIGRATIONS_DIR}..."
for FILE in $(ls "${MIGRATIONS_DIR}"/*.sql | sort); do
  FILENAME=$(basename "$FILE")
  SQL=$(cat "$FILE")
  echo "  ↳ ${FILENAME}"
  RESULT=$(
    _cf -X POST "${BASE}/${DB_ID}/query" \
        -d "$(python3 -c "import json,sys; print(json.dumps({'sql': open('${FILE}').read(), 'params': []}))")"
  )
  SUCCESS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success', False))")
  if [ "$SUCCESS" != "True" ]; then
    echo "  ✗ Migration failed:"
    echo "$RESULT" | python3 -m json.tool
    exit 1
  fi
  echo "    ✓ OK"
done

# ---------------------------------------------------------------------------
# 3. Print summary
# ---------------------------------------------------------------------------
echo ""
echo "✅ D1 setup complete!"
echo ""
echo "Add to your .env (or Streamlit secrets):"
echo ""
echo "  STORAGE_BACKEND=d1"
echo "  CF_API_TOKEN=${CF_API_TOKEN}"
echo "  CF_ACCOUNT_ID=${CF_ACCOUNT_ID}"
echo "  CF_D1_DATABASE_ID=${DB_ID}"
echo ""
echo "Update wrangler.toml (optional, for wrangler CLI use):"
echo "  database_id = \"${DB_ID}\""
