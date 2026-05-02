#!/usr/bin/env bash
# Sprint 3 / S3-5: schema-parity verification.
#
# Spins up two ephemeral PG 16 containers, applies (a) the legacy raw-SQL
# bootstrap and (b) `alembic upgrade head` against fresh DBs, and diffs
# the resulting catalogues. Exits 0 on schema parity, non-zero otherwise.
#
# The script is what we run before stamping prod (Lockin decision #3).
# It also fronts the alembic upgrade → downgrade -1 → upgrade round-trip
# so a missing downgrade in the baseline migration fails the gate too.
#
# Requirements: docker, psql in PATH, uv installed inside the repo.
#
# Usage:  ./scripts/verify_alembic_parity.sh
#         (no args; uses docker-managed throwaway containers)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

CID_RAW=""
CID_ALEMBIC=""

cleanup() {
    [[ -n "$CID_RAW"     ]] && docker rm -f "$CID_RAW"     >/dev/null 2>&1 || true
    [[ -n "$CID_ALEMBIC" ]] && docker rm -f "$CID_ALEMBIC" >/dev/null 2>&1 || true
}
trap cleanup EXIT

start_pg() {
    local name="$1"
    local port="$2"
    docker run -d --rm \
        --name "$name" \
        -e POSTGRES_PASSWORD=parity \
        -e POSTGRES_USER=parity \
        -e POSTGRES_DB=parity \
        -p "$port":5432 \
        postgres:16-alpine >/dev/null
    # Wait for ready
    for _ in $(seq 1 30); do
        if docker exec "$name" pg_isready -U parity >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    echo "ERROR: $name failed to start" >&2
    docker logs "$name" >&2 || true
    return 1
}

dump_schema() {
    local container="$1"
    local out="$2"
    docker exec -e PGPASSWORD=parity "$container" \
        pg_dump -U parity -d parity --schema-only --no-owner --no-privileges \
        > "$out"
    # Normalise volatile lines (timestamps, tablespace names) so the diff
    # only catches structural drift.
    sed -i.bak \
        -e '/^-- Dumped/d' \
        -e '/^-- Started on/d' \
        -e '/^SET /d' \
        -e '/^SELECT pg_catalog/d' \
        -e '/^--$/d' \
        -e '/^$/d' \
        "$out"
    rm -f "$out.bak"
}

echo "==> Starting PG containers..."
CID_RAW="bsgw-parity-raw-$$"
CID_ALEMBIC="bsgw-parity-alembic-$$"
start_pg "$CID_RAW"     55501
start_pg "$CID_ALEMBIC" 55502

echo "==> Applying raw-SQL schema to $CID_RAW..."
# Order = bsgateway/core/migrate.py::run_migrations
RAW_SQL_ORDER=(
    "bsgateway/routing/sql/schema.sql"
    "bsgateway/routing/sql/tenant_schema.sql"
    "bsgateway/routing/sql/rules_schema.sql"
    "bsgateway/routing/sql/feedback_schema.sql"
    "bsgateway/routing/sql/audit_schema.sql"
    "bsgateway/routing/sql/apikey_schema.sql"
    "bsgateway/executor/sql/executor_schema.sql"
)
for f in "${RAW_SQL_ORDER[@]}"; do
    docker exec -i -e PGPASSWORD=parity "$CID_RAW" \
        psql -U parity -d parity -v ON_ERROR_STOP=1 -q < "$f" >/dev/null
done

echo "==> Applying alembic upgrade head to $CID_ALEMBIC..."
DATABASE_URL="postgresql://parity:parity@127.0.0.1:55502/parity" \
    uv run alembic upgrade head

echo "==> Round-trip: alembic downgrade -1 → upgrade head..."
DATABASE_URL="postgresql://parity:parity@127.0.0.1:55502/parity" \
    uv run alembic downgrade -1
DATABASE_URL="postgresql://parity:parity@127.0.0.1:55502/parity" \
    uv run alembic upgrade head

echo "==> Dumping schemas..."
DUMP_RAW="$(mktemp)"
DUMP_ALEMBIC="$(mktemp)"
dump_schema "$CID_RAW"     "$DUMP_RAW"
dump_schema "$CID_ALEMBIC" "$DUMP_ALEMBIC"

echo "==> Diffing schemas..."
# Drop the alembic_version table from the alembic dump so we are comparing
# the user schema only. Only filter the immediately-preceding header
# comment + the CREATE/ALTER/COPY blocks for that one object — overly
# broad substring matches will accidentally drop user-table CONSTRAINT
# lines whose header comment was on the previous line.
ALEMBIC_USER="$(mktemp)"
python3 - "$DUMP_ALEMBIC" "$ALEMBIC_USER" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
lines = open(src).read().splitlines()
out = []
i = 0
n = len(lines)
DROP_OBJECT_NAMES = {"alembic_version", "alembic_version_pkc"}
while i < n:
    line = lines[i]
    # Restrict/unrestrict pragmas vary per dump (random nonce); strip them.
    if line.startswith("\\restrict") or line.startswith("\\unrestrict"):
        i += 1
        continue
    # Skip "-- Name: <name>; Type: ..." header + the following statement
    # (until the next terminating ';' on its own line).
    m = re.match(r"^-- Name: ([^;]+); Type:", line)
    if m:
        # The "Name:" header packs both the table name and (for
        # CONSTRAINT/INDEX entries) the constraint name; tokens like
        # "alembic_version" or "alembic_version_pkc" appearing anywhere
        # in the slug mean the following statement targets the alembic
        # bookkeeping table — drop it.
        slug_tokens = set(m.group(1).split())
        if slug_tokens & DROP_OBJECT_NAMES:
            i += 1
            while i < n:
                stmt_line = lines[i]
                i += 1
                if stmt_line.rstrip().endswith(";"):
                    break
            continue
    out.append(line)
    i += 1
open(dst, "w").write("\n".join(out) + "\n")
PY
# Also strip restrict pragmas from the raw dump (they include a random nonce).
DUMP_RAW_CLEAN="$(mktemp)"
grep -v -E '^\\(un)?restrict' "$DUMP_RAW" > "$DUMP_RAW_CLEAN"
DUMP_RAW="$DUMP_RAW_CLEAN"

if diff -u "$DUMP_RAW" "$ALEMBIC_USER"; then
    echo "==> SCHEMA PARITY: OK (raw-SQL == alembic upgrade head)"
    exit 0
else
    echo "==> SCHEMA PARITY: FAILED — see diff above" >&2
    echo "    Raw dump:     $DUMP_RAW" >&2
    echo "    Alembic dump: $ALEMBIC_USER" >&2
    exit 1
fi
