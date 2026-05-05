#!/bin/bash
# Wrapper to launch the native messaging host.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
exec "$DIR/.venv/bin/python" -m host.main
