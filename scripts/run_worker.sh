#!/usr/bin/env bash
set -euo pipefail

celery -A app.tasks.celery_app worker -l INFO
