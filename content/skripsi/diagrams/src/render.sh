#!/usr/bin/env bash
# Render the thesis diagrams from local Mermaid sources.
# Each source produces a vector SVG master and a PDF for pdflatex; nothing is
# fetched from the network at render time.
# Tested with @mermaid-js/mermaid-cli 11.15.0.
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]; then
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    chromium chromium-browser google-chrome; do
    if [ -x "$candidate" ]; then
      export PUPPETEER_EXECUTABLE_PATH="$candidate"
      break
    elif command -v "$candidate" >/dev/null 2>&1; then
      export PUPPETEER_EXECUTABLE_PATH="$(command -v "$candidate")"
      break
    fi
  done
fi
if [ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]; then
  echo "Chrome or Chromium not found; set PUPPETEER_EXECUTABLE_PATH" >&2
  exit 1
fi

for source in ./*.mmd; do
  name="${source%.mmd}"
  name="${name#./}"
  mmdc -i "$source" -o "../${name}.svg" -c mermaid-config.json -b white --quiet
  mmdc -i "$source" -o "../${name}.pdf" -c mermaid-config.json -f --quiet
  echo "rendered ${name}.svg and ${name}.pdf"
done
