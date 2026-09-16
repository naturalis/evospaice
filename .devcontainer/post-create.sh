#!/usr/bin/env bash
set -euo pipefail

VENV_DIR="${PWD}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"

echo "==> Installing system packages..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends bubblewrap socat
sudo rm -rf /var/lib/apt/lists/*

BLAST_VERSION="2.17.0"
echo "==> Installing NCBI BLAST+ ${BLAST_VERSION} from NCBI..."
wget -q "https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/${BLAST_VERSION}/ncbi-blast-${BLAST_VERSION}+-x64-linux.tar.gz" -O /tmp/blast.tar.gz
sudo tar -xzf /tmp/blast.tar.gz -C /usr/local --strip-components=1
rm /tmp/blast.tar.gz

echo "==> BLAST+ version:"
blastn -version

echo "==> Installing AzCopy..."
wget -q "https://aka.ms/downloadazcopy-v10-linux" -O /tmp/azcopy.tar.gz
tar -xzf /tmp/azcopy.tar.gz -C /tmp
sudo cp /tmp/azcopy_linux_*/azcopy /usr/local/bin/
sudo chmod +x /usr/local/bin/azcopy
rm -rf /tmp/azcopy.tar.gz /tmp/azcopy_linux_*
echo "==> AzCopy version:"
azcopy --version

GITLEAKS_VERSION="8.21.2"
echo "==> Installing Gitleaks ${GITLEAKS_VERSION}..."
case "$(uname -m)" in
    x86_64) GITLEAKS_ARCH="x64" ;;
    aarch64 | arm64) GITLEAKS_ARCH="arm64" ;;
    *) GITLEAKS_ARCH="$(uname -m)" ;;
esac
GITLEAKS_TARBALL="gitleaks_${GITLEAKS_VERSION}_linux_${GITLEAKS_ARCH}.tar.gz"
GITLEAKS_BASE_URL="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
wget -q "${GITLEAKS_BASE_URL}/${GITLEAKS_TARBALL}" -O /tmp/gitleaks.tar.gz
# Verify the download against the published checksums file from the same release.
# Abort if the checksum is missing or does not match (supply-chain protection).
wget -q "${GITLEAKS_BASE_URL}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" -O /tmp/gitleaks_checksums.txt
GITLEAKS_EXPECTED_SHA="$(grep " ${GITLEAKS_TARBALL}\$" /tmp/gitleaks_checksums.txt | awk '{print $1}')"
if [ -z "${GITLEAKS_EXPECTED_SHA}" ]; then
    echo "ERROR: no checksum found for ${GITLEAKS_TARBALL} in the Gitleaks release checksums file." >&2
    exit 1
fi
echo "${GITLEAKS_EXPECTED_SHA}  /tmp/gitleaks.tar.gz" | sha256sum --check --status \
    || { echo "ERROR: Gitleaks checksum verification failed for ${GITLEAKS_TARBALL}." >&2; exit 1; }
echo "==> Gitleaks checksum verified."
tar -xzf /tmp/gitleaks.tar.gz -C /tmp gitleaks
sudo install -m 0755 /tmp/gitleaks /usr/local/bin/gitleaks
rm -f /tmp/gitleaks.tar.gz /tmp/gitleaks_checksums.txt /tmp/gitleaks
echo "==> Gitleaks version:"
gitleaks version

echo "==> Installing pandoc and LaTeX for PDF generation..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    pandoc \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-plain-generic \
    lmodern
sudo apt-get clean
sudo rm -rf /var/lib/apt/lists/*

echo "==> Creating project virtual environment at ${VENV_DIR}..."
if [ ! -x "${PYTHON_BIN}" ]; then
    # Use --system-site-packages so the base image's preinstalled libraries
    # (PyTorch, CUDA, transformers, ...) remain available in the default interpreter.
    # This is a deliberate tradeoff: the venv inherits the base image's GPU stack
    # instead of reinstalling multi-GB, CUDA-matched wheels on every container build.
    # It intentionally accepts reduced reproducibility for the dev container; the
    # deterministic, torch-free dependency set for CI lives in requirements.txt.
    /opt/conda/bin/python -m venv --system-site-packages "${VENV_DIR}"
fi
"${PYTHON_BIN}" -m pip install --no-cache-dir --upgrade pip

echo "==> Installing Python requirements..."
if [ -f requirements.txt ]; then
    "${PYTHON_BIN}" -m pip install --no-cache-dir -r requirements.txt
fi

echo "==> Installing project package with dev dependencies (pytest, linters)..."
if [ -f pyproject.toml ]; then
    "${PYTHON_BIN}" -m pip install --no-cache-dir -e ".[dev]"
fi

export PATH="$HOME/.local/bin:$PATH"
echo "==> Setting up pre-commit hooks..."
# Install hooks with the same interpreter that provides pre-commit (from ".[dev]"),
# because hooks hardcode INSTALL_PYTHON to the Python used during 'pre-commit install'.
if [ -f .pre-commit-config.yaml ]; then
    "${PYTHON_BIN}" -m pre_commit install --install-hooks --hook-type pre-commit --hook-type pre-push
fi

echo "==> Post-create setup complete."
