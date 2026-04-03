#!/usr/bin/env sh
# Raspberry / Debian Buster (o seccomp datato): BuildKit può rifiutare RUN --security=insecure
# se il daemon ignora daemon.json. --allow security.insecure sul client abilita l'entitlement
# solo per questo build (Docker 23+ / buildx).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
IMAGE="${IMAGE:-cf-googlebot-archiver:local}"
export DOCKER_BUILDKIT=1
docker buildx build --load --allow security.insecure -f raspberry-buster/Dockerfile -t "$IMAGE" .
docker compose -f docker-compose.yml -f raspberry-buster/docker-compose.buster.yml up -d
