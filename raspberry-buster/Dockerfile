# syntax=docker/dockerfile:1
# Variante per host con seccomp datati (es. Raspberry Pi + Debian Buster): pip durante il build
# e Python a runtime possono fallire con PermissionError su time.time() senza questi accorgimenti.
# Vedi README in questa cartella. Build context = root del repository.
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN --security=insecure pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

EXPOSE 418

CMD ["python", "-m", "app.server"]
