#!/usr/bin/env bash
# Evaluasi observasi tersimpan; tidak menjalankan polling langsung.
set -euo pipefail
exec python3 "$(dirname "$0")/instruments.py" metrics "$@"
