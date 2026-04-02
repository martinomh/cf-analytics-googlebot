#!/usr/bin/env sh
# Debian Buster / kernel datati: seccomp del daemon può far fallire pip con PermissionError su time.time()
# mentre importa logging. Il builder classico + seccomp=unconfined evita build.privileged (che con BuildKit
# richiede entitlement security.insecure spesso disabilitata sul daemon).
set -e
cd "$(dirname "$0")"
IMAGE="${IMAGE:-cf-googlebot-archiver:local}"
export DOCKER_BUILDKIT=0
docker build --security-opt seccomp=unconfined -t "$IMAGE" .
docker compose up -d
