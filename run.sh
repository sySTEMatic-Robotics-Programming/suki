#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
