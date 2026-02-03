#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo "Missing .env. Copy .env.example to .env and edit values." >&2
  exit 1
fi

docker compose pull
# Build only if Dockerfile exists
if [ -f Dockerfile ]; then
  docker compose build
fi

docker compose up -d

docker compose ps
