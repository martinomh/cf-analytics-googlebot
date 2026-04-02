#!/usr/bin/env sh
# Raspberry / Debian Buster: BuildKit rifiuta RUN --security=insecure se il daemon ignora daemon.json.
# --allow security.insecure sul client abilita quell'entitlement per questo solo build (Docker 23+ / buildx).
set -e
cd "$(dirname "$0")"
IMAGE="${IMAGE:-cf-googlebot-archiver:local}"
export DOCKER_BUILDKIT=1
docker buildx build --load --allow security.insecure -f Dockerfile.buster -t "$IMAGE" .
docker compose up -d
