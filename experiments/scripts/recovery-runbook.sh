#!/usr/bin/env bash
# Verifikasi hasil koreksi dan reset tersimpan; tidak menjalankan pemulihan.
set -euo pipefail
exec python3 "$(dirname "$0")/instruments.py" recovery "$@"
