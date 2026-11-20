# Ảnh dùng chung cho mọi dịch vụ backend; mỗi container chạy một dịch vụ (xem docker-compose.yml).
# Xây dựng offline: đặt wheel vào backend/wheels/ (scripts/build-wheelhouse.sh) và đặt PIP_OFFLINE=1.
FROM python:3.12-slim-bookworm

ARG PIP_OFFLINE=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/backend

RUN apt-get update && apt-get install -y --no-install-recommends git pandoc curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 app && useradd -u 10001 -g app -m -s /usr/sbin/nologin app

WORKDIR /app/backend
COPY backend/requirements.txt ./
COPY backend/wheels* /tmp/wheels/
RUN if [ "$PIP_OFFLINE" = "1" ]; then \
      pip install --no-index --find-links /tmp/wheels -r requirements.txt; \
    else pip install -r requirements.txt; fi && rm -rf /tmp/wheels

COPY backend/aicommon ./aicommon
COPY backend/services ./services
COPY backend/tools ./tools
COPY prompts /app/prompts
COPY skills /app/skills
COPY glossary /app/glossary
COPY support /app/support
COPY config/users.dev.yaml /app/config/users.dev.yaml

RUN mkdir -p /data /kb && chown -R app:app /data /kb
USER app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "uvicorn", "services.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
