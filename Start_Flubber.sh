#!/usr/bin/env bash
set -euo pipefail
flubber_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$flubber_dir/companion"
if command -v python3.12 >/dev/null 2>&1; then
  flubber_python=python3.12
else
  flubber_python=python3
fi
"$flubber_python" -c 'import sys; assert sys.version_info >= (3,11), "Install Python 3.12 or newer first."'
if [ ! -x .venv/bin/python ]; then "$flubber_python" -m venv .venv; fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python configure.py --if-missing
exec .venv/bin/python run.py
