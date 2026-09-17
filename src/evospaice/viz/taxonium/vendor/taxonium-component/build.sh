#!/usr/bin/env bash
set -euo pipefail

vendor_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$vendor_dir/source"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to build the Taxonium component." >&2
  exit 1
fi

docker run --rm \
  -e HOST_UID="$(id -u)" \
  -e HOST_GID="$(id -g)" \
  -v "$source_dir:/source:ro" \
  -v "$vendor_dir:/output" \
  node:22-bookworm \
  sh -euc '
    cp -a /source/. /build/
    cd /build/taxonium_component
    npm install --global npm@11.4.0
    npm ci
    npm run check-types
    npm run build
    cp dist/taxonium-component.es.js /output/taxonium-component.es.js
    if test -f dist/taxonium-component.es.js.map; then
      cp dist/taxonium-component.es.js.map /output/taxonium-component.es.js.map
    fi
    chown "$HOST_UID:$HOST_GID" /output/taxonium-component.es.js*
  '
