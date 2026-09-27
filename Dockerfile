FROM python:3.12-slim

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      PYTHONPATH=/app \
      PIP_NO_CACHE_DIR=1 \
      PIP_DISABLE_PIP_VERSION_CHECK=1

  WORKDIR /app

  RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      g++ \
      libpq-dev \
      libffi-dev \
      libssl-dev \
      libcairo2 \
      python3-dev \
      curl \
      && rm -rf /var/lib/apt/lists/*

  COPY requirements_fixed.txt .
  RUN pip install --upgrade pip setuptools wheel && pip install -r requirements_fixed.txt \
      && python -m playwright install --with-deps chromium

  COPY . .

  RUN mkdir -p sessions data/training logs

  EXPOSE 10000

  # Increased start-period to 120s: alembic + uvicorn startup can take 60-90s on free tier
  HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
      CMD curl -f http://localhost:${PORT:-10000}/api/healthz || exit 1

  CMD ["bash", "start.sh"]
  