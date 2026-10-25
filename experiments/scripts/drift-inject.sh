#!/usr/bin/env bash
# Verifikasi bukti penerimaan satu injeksi; tidak mengirim mutasi.
set -euo pipefail
exec python3 "$(dirname "$0")/instruments.py" injection "$@"
