#!/bin/bash
set -e

echo "=== Setting up database ==="

if [ -z "$DATABASE_URL" ]; then
    export DATABASE_URL="postgresql+asyncpg://postgres:changeme@localhost:5432/telegram_agent"
fi

echo "Running Alembic migrations..."
cd /app
alembic upgrade head

echo "Database setup complete!"
