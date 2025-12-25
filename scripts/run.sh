#!/bin/bash
# Run claude-continue daemon manually

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate venv if exists
if [[ -d "venv" ]]; then
    source venv/bin/activate
fi

# Run daemon
python src/daemon.py "$@"
