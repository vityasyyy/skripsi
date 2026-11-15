#!/usr/bin/env bash
# Render the thesis diagrams from local HTML/CSS/SVG sources.
# Canvas width is 1600 px and the device scale factor is 2, so each PNG is
# 3200 px wide. At the thesis text width (14.3 cm) this is above 500 dpi.
set -euo pipefail
cd "$(dirname "$0")"

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
if [ ! -x "$CHROME" ]; then
  for candidate in chromium chromium-browser google-chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME="$(command -v "$candidate")"
      break
    fi
  done
fi
if [ ! -x "$CHROME" ]; then
  echo "Chrome or Chromium not found; set CHROME=/path/to/binary" >&2
  exit 1
fi

render() {
  local name="$1"
  local height="$2"
  "$CHROME" \
    --headless=new \
    --disable-gpu \
    --hide-scrollbars \
    --default-background-color=FFFFFFFF \
    --force-device-scale-factor=2 \
    --window-size="1600,${height}" \
    --screenshot="../${name}.png" \
    "file://${PWD}/${name}.html" >/dev/null 2>&1
  test -s "../${name}.png"
  echo "rendered ${name}.png"
}

render fig-control-loop 1010
render fig-pipeline 1150
render fig-runtime-architecture 1000
render fig-drift-scenarios 1040
render fig-measurement-timeline 960
render fig-analysis-flow 1010
render fig-deployment-reconciliation 1020
