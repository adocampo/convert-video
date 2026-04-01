#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# dev.sh — Enter the development environment
# 
# Usage: bash dev.sh  (NOT source dev.sh)
#
# This script:
# 1. Creates a .venv/ if it doesn't exist
# 2. Activates the venv
# 3. Installs convert-video in editable mode
# 4. Spawns an interactive shell with the venv active
# 5. Both convert-video-dev and convert-video commands are available
# ──────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()  { echo -e "${GREEN}[✓] $*${RESET}"; }
warn()  { echo -e "${YELLOW}[!] $*${RESET}"; }
fail()  { echo -e "${RED}[✗] $*${RESET}" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

# ── Create venv if it doesn't exist ──────────
if [[ ! -d "${VENV_DIR}" ]]; then
    info "Creating virtual environment in .venv/"
    python3 -m venv "${VENV_DIR}"
fi

# ── Activate ─────────────────────────────────
source "${VENV_DIR}/bin/activate"
info "Activated venv: ${VENV_DIR}"

# ── Install in editable mode ─────────────────
info "Installing convert-video in editable mode (pip install -e .)..."
if pip install -e "${SCRIPT_DIR}" --quiet; then
    info "Ready! convert-video-dev is now running from source."
    echo -e "${YELLOW}  Any changes to src/ take effect immediately.${RESET}"
    echo ""
    echo -e "  Run:  ${GREEN}convert-video-dev --version${RESET}    to verify"
    echo -e "  Run:  ${GREEN}convert-video-dev --help${RESET}       for usage"
    echo -e "  Run:  ${GREEN}deactivate${RESET}                     to leave the venv"
    echo ""
else
    fail "Failed to install convert-video in editable mode"
fi

# ── Drop into a subshell with venv active ────
exec "${SHELL}"
