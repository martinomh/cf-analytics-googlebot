# Multi-arch: docker buildx build --platform linux/arm/v7,linux/arm64,linux/amd64 .
# Debian slim (glibc): su Raspberry Pi armv7 Alpine+Python 3.12 può far crashare pip (es. exit 139 / SIGSEGV).
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

EXPOSE 418

CMD ["python", "-m", "app.server"]
