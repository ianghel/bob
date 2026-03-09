# ============================================================
# Stage 1 — Build React frontend
# ============================================================
FROM node:20-slim AS frontend-builder

WORKDIR /app/bob-ui
COPY bob-ui/package.json bob-ui/package-lock.json ./
RUN npm ci
COPY bob-ui/ ./
RUN npm run build

# ============================================================
# Stage 2 — Python API runtime
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# System dependencies for aiomysql and python-magic
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libmariadb-dev \
       libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY api/ api/
COPY core/ core/
COPY alembic/ alembic/
COPY alembic.ini pyproject.toml ./

# Built frontend assets
COPY --from=frontend-builder /app/bob-ui/dist bob-ui/dist

# Run as non-root
RUN useradd -m -r bob && chown -R bob:bob /app
USER bob

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
