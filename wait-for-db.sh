#!/bin/sh
set -e

# Load only DB-related keys from .env (do not `source` .env — files often contain values
# that are valid for dotenv but are not POSIX shell, which causes "command not found").
if [ -f /app/.env ]; then
  _db_env_exports=$(python3 <<'PY'
from pathlib import Path
import shlex

try:
    from dotenv import dotenv_values
except ImportError:
    raise SystemExit(0)

p = Path("/app/.env")
if not p.is_file():
    raise SystemExit(0)

d = dotenv_values(p)
for k in ("ENVIRONMENT", "ENV", "PROD_HOST", "PROD_PORT", "PROD_USER", "PROD_PASSWORD", "PROD_DB"):
    if k not in d or d[k] is None:
        continue
    print(f"export {k}={shlex.quote(str(d[k]))}")
PY
  )
  if [ -n "$_db_env_exports" ]; then
    eval "$_db_env_exports"
  fi
fi

# Same precedence as config.database_config.resolve_database_url() for the probe only.
env_name=$(printf '%s' "${ENVIRONMENT:-${ENV:-}}" | tr '[:upper:]' '[:lower:]')
prod_complete=0
if [ -n "${PROD_HOST:-}" ] && [ -n "${PROD_USER:-}" ] && [ -n "${PROD_DB:-}" ]; then
  prod_complete=1
fi

if { [ "$env_name" = "prod" ] || [ "$env_name" = "production" ]; } && [ "$prod_complete" -eq 1 ]; then
  DB_HOST="${PROD_HOST}"
  DB_PORT="${PROD_PORT:-5432}"
  DB_USER="${PROD_USER}"
  DB_NAME="${PROD_DB}"
  DB_PASSWORD="${PROD_PASSWORD:-}"
else
  : "${POSTGRES_HOST:?Missing POSTGRES_HOST (or use ENVIRONMENT=prod with PROD_HOST, PROD_USER, PROD_DB)}"
  : "${POSTGRES_PORT:?Missing POSTGRES_PORT}"
  : "${POSTGRES_USER:?Missing POSTGRES_USER}"
  : "${POSTGRES_PASSWORD:?Missing POSTGRES_PASSWORD}"
  : "${POSTGRES_DB:?Missing POSTGRES_DB}"
  DB_HOST="${POSTGRES_HOST}"
  DB_PORT="${POSTGRES_PORT}"
  DB_USER="${POSTGRES_USER}"
  DB_NAME="${POSTGRES_DB}"
  DB_PASSWORD="${POSTGRES_PASSWORD}"
fi

# RDS and many cloud Postgres endpoints require TLS.
case "$DB_HOST" in
  *.rds.amazonaws.com|*.rds.amazonaws.com.cn)
    export PGSSLMODE="${PGSSLMODE:-require}"
    ;;
esac

echo "Waiting for PostgreSQL to be ready at ${DB_HOST}:${DB_PORT} (PGSSLMODE=${PGSSLMODE:-default})..."

export PGPASSWORD="${DB_PASSWORD}"

max_retries=60
retry_count=0

until psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -w -c '\q' >/dev/null 2>&1; do
  retry_count=$((retry_count + 1))
  if [ "$retry_count" -ge "$max_retries" ]; then
    echo "PostgreSQL is still unavailable after $max_retries attempts"
    echo "Last error:"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -w -c '\q' 2>&1 || true
    exit 1
  fi
  echo "PostgreSQL is unavailable - sleeping (attempt $retry_count/$max_retries)"
  sleep 2
done

echo "PostgreSQL is up - executing command"

# Under `set -e` an unconfigured migration run exits non-zero and takes the container
# down before the app ever starts, so the step is gated on a real config.
#
# Runs migrate.py rather than `alembic upgrade head`: migrations are split into one
# branch per product, so there are several heads and `head` is ambiguous. migrate.py
# upgrades core first, then only the products enabled in core.installed_products.
alembic_config="${ALEMBIC_CONFIG:-/app/alembic.ini}"
if [ -f "$alembic_config" ]; then
  echo "Running database migrations..."
  ALEMBIC_CONFIG="$alembic_config" python3 /app/migrate.py
else
  echo "Skipping migrations: no Alembic config at $alembic_config"
fi

exec "$@"
