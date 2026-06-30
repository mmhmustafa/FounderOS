#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python="$repository_root/.venv/bin/python"

if [ ! -x "$python" ]; then
    echo "Virtual environment not found. Run: python3 -m venv .venv" >&2
    exit 1
fi

cd "$repository_root"
exec "$python" -m pytest -vv --durations=10
