#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
fi
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
