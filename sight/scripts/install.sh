#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3.12 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements-bootstrap.lock
.venv/bin/python -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements.lock
.venv/bin/python -m pip check
.venv/bin/python -m sight_core.cli doctor
