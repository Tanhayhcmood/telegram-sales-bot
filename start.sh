#!/bin/bash
  # No set -e — we handle errors explicitly

  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "$SCRIPT_DIR"

  export SECRET_KEY="${SECRET_KEY:-change-this-secret-key-in-production}"
  export API_KEY="${API_KEY:-change-this-api-key-in-production}"
  # Redis is optional on Render; the app uses in-process fakeredis when unset.
  # Do not point production at a nonexistent localhost Redis server.
  export REDIS_URL="${REDIS_URL:-}"
  export REDIS_QUEUE_URL="${REDIS_QUEUE_URL:-}"

  # Fix DATABASE_URL format for asyncpg (only if DATABASE_URL is non-empty)
  if [ -n "${DATABASE_URL:-}" ]; then
    DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|postgresql://|postgresql+asyncpg://|g; s|postgres://|postgresql+asyncpg://|g')
    DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|?sslmode=disable||g; s|&sslmode=disable||g; s|?sslmode=require||g; s|&sslmode=require||g')
    export DATABASE_URL
    echo "[start] DATABASE_URL driver: ${DATABASE_URL%%://*}"
  else
    echo "[start] ERROR: DATABASE_URL is not set; refusing to use a local fallback." >&2
    exit 1
  fi

  mkdir -p sessions data/training logs

  # ── Reconcile databases created by older releases ──────────────────────────
  # Older releases called SQLAlchemy create_all() during app startup.  If that
  # happened before Alembic ran, the schema is complete but alembic_version is
  # missing.  The helper only stamps a schema after verifying every model table
  # and column exists; fresh or partial databases still use normal migrations.
  echo "[start] Checking migration state..."
  PREPARE_STATUS=0
  python3 scripts/prepare_migrations.py || PREPARE_STATUS=$?
  if [ "$PREPARE_STATUS" -ne 0 ] && [ "$PREPARE_STATUS" -ne 10 ]; then
    echo "[start] ERROR: Could not prepare migration state." >&2
    exit 1
  fi

  # ── Run DB migrations (retry up to 3 times with back-off) ───────────────────
  MIGRATION_OK=0
  if [ "$PREPARE_STATUS" -eq 10 ]; then
    MIGRATION_OK=1
    echo "[start] Legacy schema stamped at current head; no upgrade needed."
  else
    echo "[start] Running DB migrations..."
    for attempt in 1 2 3; do
      echo "[start] Migration attempt $attempt/3..."
      if timeout 60 env -u PYTHONPATH alembic upgrade head; then
        MIGRATION_OK=1
        echo "[start] Migrations succeeded on attempt $attempt."
        break
      fi
      echo "[start] Migration attempt $attempt failed."
      [ "$attempt" -lt 3 ] && sleep 10
    done
  fi

  if [ "$MIGRATION_OK" -ne 1 ]; then
    echo "[start] ERROR: Migrations failed after 3 attempts; refusing to serve with an unknown schema." >&2
    exit 1
  fi

  # ── Start the app only after the schema is ready ────────────────────────────
  # This prevents lifespan tasks (userbot, schedulers, and maintenance jobs)
  # from querying tables while Alembic is still creating them.
  echo "[start] Starting server on port ${PORT:-10000}..."
  exec python3 -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-10000}" \
    --log-level info \
    --loop asyncio
