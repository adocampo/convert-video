#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# dev.sh — Enter the development environment
# Creates a venv, installs in editable mode,
# and drops you into an activated shell.
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
pip install -e "${SCRIPT_DIR}" --quiet

info "Ready! convert-video is now running from source."
echo -e "${YELLOW}  Any changes to src/ take effect immediately.${RESET}"
echo ""
echo -e "  Run:  ${GREEN}convert-video-dev --version${RESET}    to verify"
echo -e "  Run:  ${GREEN}convert-video-dev --help${RESET}       for usage"
echo -e "  Run:  ${GREEN}deactivate${RESET}                     to leave the venv"
echo ""

# ── Drop into a subshell with venv active ────
exec "${SHELL}"
