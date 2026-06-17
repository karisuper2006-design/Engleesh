#!/usr/bin/env bash
# Engleesh launcher — macOS (double-clickable .command file)

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

xattr -d com.apple.quarantine "$0" 2>/dev/null || true

# Find Python 3
PYTHON=""
for p in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 python3; do
    if command -v "$p" &>/dev/null; then
        PYTHON="$p"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3 not found."
    echo "Install from https://www.python.org/downloads/"
    read -p "Press Enter to close..."
    exit 1
fi

PYVER="$($PYTHON --version 2>&1)"
echo "Using: $PYTHON ($PYVER)"

# Check if venv is valid (has working python3)
VENV_OK=0
if [ -d "venv" ] && [ -f "venv/bin/python3" ]; then
    if "venv/bin/python3" -c "print('ok')" 2>/dev/null | grep -q "ok"; then
        VENV_OK=1
    fi
fi

if [ "$VENV_OK" -eq 0 ]; then
    echo "Creating fresh virtual environment..."
    rm -rf venv
    "$PYTHON" -m venv venv
fi

VENV_PIP="venv/bin/pip3"
VENV_PY="venv/bin/python3"

echo "Installing dependencies..."
"$VENV_PIP" install -q -r requirements.txt 2>&1

echo "Starting Engleesh..."
"$VENV_PY" app.py

if [ $? -ne 0 ]; then
    echo ""
    echo "Application exited with an error."
    read -p "Press Enter to close..."
fi
