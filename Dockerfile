# Socratic Bots backend: multi-stage build, non-root runtime.

FROM python:3.13-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt


FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# libpq5: psycopg2. Pango, HarfBuzz and a font: WeasyPrint, which the app imports at startup.
# curl: the health check.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    fonts-dejavu-core \
    shared-mime-info \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 socraticbots \
    && useradd --uid 1001 --gid socraticbots --create-home --shell /usr/sbin/nologin socraticbots

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=socraticbots:socraticbots . .

# WhiteNoise serves these from the image, so they never go stale in a volume.
RUN python backend/manage.py collectstatic --noinput \
    && chmod +x docker/entrypoint.sh

USER socraticbots

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
