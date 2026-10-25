#!/usr/bin/env bash
# Validasi bukti baseline tersimpan; tidak mengakses klaster.
set -euo pipefail
exec python3 "$(dirname "$0")/instruments.py" baseline "$@"
