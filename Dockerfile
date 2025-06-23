# syntax=docker/dockerfile:1.5
FROM python:3.12-alpine AS builder

# musl-based build tools
RUN apk add --no-cache \
      build-base \
      libffi-dev \
      openssl-dev \
      musl-dev \
      python3-dev

WORKDIR /src
COPY requirements.txt .

# cache your pip downloads with BuildKit
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

FROM python:3.12-alpine AS runtime
RUN adduser --disabled-password --gecos '' appuser
WORKDIR /app

# install only Alpine-compatible wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
  && rm -rf /wheels

COPY --chown=appuser:appuser prospect_cleaner/ ./prospect_cleaner/
COPY --chown=appuser:appuser main.py ./

USER appuser

EXPOSE 8000
CMD ["gunicorn","-k","uvicorn.workers.UvicornWorker","main:app","--bind","0.0.0.0:8000","--workers","4"]
