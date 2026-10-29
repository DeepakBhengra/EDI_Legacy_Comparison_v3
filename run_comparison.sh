#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f compare_segments.py ]]; then
  echo "This launcher must stay in the project folder, next to compare_segments.py."
  read -r -p "Press Enter to close..."
  exit 1
fi

if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  echo "Creating .venv ..."
  python3 -m venv .venv
  PY=".venv/bin/python"
else
  echo "Python 3.10 or later was not found. Install python3, then run this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! "$PY" -c "import xlsxwriter, paramiko" >/dev/null 2>&1; then
  echo "Installing packages into .venv. This happens once."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
fi

echo
echo "Starting compare_segments.py"
set +e
"$PY" compare_segments.py "$@"
status=$?
set -e
echo
if [[ "$status" -ne 0 ]]; then
  echo "The comparison exited with code $status."
fi
read -r -p "Press Enter to close..."
exit "$status"
