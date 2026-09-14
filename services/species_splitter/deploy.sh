#!/usr/bin/env bash

set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 <resource-group> <function-app-name>" >&2
  exit 2
fi

resource_group="$1"
function_app_name="$2"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
package_file="$(mktemp --suffix=.zip)"
trap 'rm -f -- "$package_file"' EXIT

command -v az >/dev/null 2>&1 || {
  echo "Azure CLI is required but was not found on PATH." >&2
  exit 1
}

python3 - "$script_dir" "$package_file" <<'PY'
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

source = Path(sys.argv[1])
destination = Path(sys.argv[2])

with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            archive.write(path, path.relative_to(source))
PY

az functionapp deployment source config-zip \
  --resource-group "$resource_group" \
  --name "$function_app_name" \
  --src "$package_file" \
  --build-remote true \
  --output none

az functionapp config appsettings set \
  --resource-group "$resource_group" \
  --name "$function_app_name" \
  --settings AzureWebJobsStorage= \
  --output none

az functionapp restart \
  --resource-group "$resource_group" \
  --name "$function_app_name" \
  --output none