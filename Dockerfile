# Multi-arch: docker buildx build --platform linux/arm/v7,linux/arm64,linux/amd64 .
FROM python:3.12-alpine

WORKDIR /app

RUN apk add --no-cache tini

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations

ENV PYTHONUNBUFFERED=1
EXPOSE 418

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["python", "-m", "app.server"]
