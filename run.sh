#!/usr/bin/env bash
# One-click start for macOS and Linux: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  Amazon UK Opportunity Finder"
echo "  ============================"
echo

find_python() {
  for cmd in python3.12 python3.11 python3.13 python3.14 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1 &&
       "$cmd" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      echo "$cmd"
      return 0
    fi
  done
  return 1
}

# 1. Virtual environment
if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "  [1/4] The existing .venv is broken or too old - recreating it ..."
  rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
  if ! PY="$(find_python)"; then
    echo "  [!] Python 3.11 or newer was not found."
    echo "      macOS: brew install python@3.12   ·   Ubuntu/Debian: sudo apt install python3 python3-venv"
    exit 1
  fi
  echo "  [1/4] Creating the virtual environment with $PY ..."
  if ! "$PY" -m venv .venv; then
    echo "  [!] Could not create the virtual environment. On Ubuntu/Debian: sudo apt install python3-venv"
    exit 1
  fi
else
  echo "  [1/4] Virtual environment found."
fi

# 2. Requirements
echo "  [2/4] Installing / checking requirements ..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

# 3. Database
echo "  [3/4] Preparing the data folder and database ..."
.venv/bin/python app.py --init-only

# 4. Start
echo "  [4/4] Starting the app at http://127.0.0.1:${AOF_PORT:-8877}"
echo
exec .venv/bin/python app.py
