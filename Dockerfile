# syntax=docker/dockerfile:1.7
# Multi-purpose image: runs either the bot (main.py) or the dashboard (streamlit).
# Select at runtime: CMD ["python", "main.py"] or CMD ["streamlit", "run", "dashboard.py"].

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISABLE_KEYCHAIN=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        tini \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt \
 && pip install "psycopg[binary]>=3.1" SQLAlchemy>=2.0 alembic>=1.13 \
                google-cloud-secret-manager>=2.20 firebase-admin>=6.5

COPY . .

RUN addgroup --system trader && adduser --system --ingroup trader trader \
 && mkdir -p /data \
 && chown -R trader:trader /app /data
USER trader

VOLUME ["/data"]

EXPOSE 8501

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "main.py"]
