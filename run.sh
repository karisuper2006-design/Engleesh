#!/usr/bin/env bash
# Engleesh launcher — Linux

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

xattr -d com.apple.quarantine "$0" 2>/dev/null || true

PYTHON=""
for p in /usr/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$p" &>/dev/null; then
        PYTHON="$p"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found."
    echo "Install: sudo apt install python3 python3-venv"
    read -p "Press Enter to close..."
    exit 1
fi

echo "Using: $PYTHON ($($PYTHON --version 2>&1))"

if [ ! -d "venv" ] || [ ! -f "venv/bin/python3" ]; then
    echo "Creating virtual environment..."
    rm -rf venv
    "$PYTHON" -m venv venv
fi

VENV_PYTHON="venv/bin/python3"
VENV_PIP="venv/bin/pip3"

echo "Installing dependencies..."
"$VENV_PIP" install -q -r requirements.txt 2>&1

echo "Starting Engleesh..."
"$VENV_PYTHON" app.py

if [ $? -ne 0 ]; then
    echo ""
    echo "Application exited with an error."
    read -p "Press Enter to close..."
fi
