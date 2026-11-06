#!/bin/sh
# Copies the spec from a local checkout of the backend repo (prod branch) into spec/openapi.json and regenerates.
#   BACKEND=../hirefinn-web-app-backend REF=refs/remotes/origin/prod ./scripts/pull-spec.sh
set -eu
cd "$(dirname "$0")/.."
BACKEND="${BACKEND:-../hirefinn-web-app-backend}"
REF="${REF:-refs/remotes/origin/prod}"
PYTHON="${PYTHON:-python3}"
git -C "$BACKEND" fetch --quiet origin prod || true
git -C "$BACKEND" show "${REF}:openapi/openapi.json" > spec/openapi.json
"$PYTHON" scripts/generate.py
