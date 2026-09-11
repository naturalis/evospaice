#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.local.yml"

has_nvidia_adapter() {
    if command -v nvidia-smi >/dev/null 2>&1; then
        if nvidia-smi -L >/dev/null 2>&1; then
            return 0
        fi
    fi

    if [ -e "/dev/nvidiactl" ] || [ -e "/dev/nvidia0" ]; then
        return 0
    fi

    return 1
}

write_cpu_override() {
    cat >"${LOCAL_COMPOSE_FILE}" <<'EOF'
services:
  app: {}
EOF
}

write_gpu_override() {
    cat >"${LOCAL_COMPOSE_FILE}" <<'EOF'
services:
  app:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
EOF
}

if has_nvidia_adapter; then
    echo "NVIDIA adapter detected. Enabling GPU reservation for devcontainer."
    write_gpu_override
else
    echo "No NVIDIA adapter detected. Using CPU-only devcontainer configuration."
    write_cpu_override
fi
