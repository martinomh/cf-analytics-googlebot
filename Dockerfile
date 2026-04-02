# Multi-arch: docker buildx build --platform linux/arm/v7,linux/arm64,linux/amd64 .
# Nessun `apk`: init PID 1 = Docker (`init: true` in compose), evita mirror Alpine fragili su alcuni Pi.
FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

ENV PYTHONUNBUFFERED=1
EXPOSE 418

CMD ["python", "-m", "app.server"]
