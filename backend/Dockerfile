FROM python:3.14-slim AS builder

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

FROM python:3.14-slim AS runtime

ARG VERSION=dev
LABEL org.opencontainers.image.title="RobotsSystem Backend" \
      org.opencontainers.image.version="$VERSION"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    APP_VERSION="$VERSION"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
RUN mkdir -p /backups \
    && chown app:app /backups \
    && chmod +x /app/entrypoint.sh

USER app
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
