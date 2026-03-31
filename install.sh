#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# install.sh — Install convert-video via pipx
# Works on Linux, macOS, and WSL
# ──────────────────────────────────────────────

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[✓] $*${RESET}"; }
warn()    { echo -e "${YELLOW}[!] $*${RESET}"; }
fail()    { echo -e "${RED}[✗] $*${RESET}" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Detect OS and package manager ────────────
detect_pkg_manager() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        command -v brew &>/dev/null && { echo "brew"; return; }
        fail "Homebrew is required on macOS. Install it from https://brew.sh"
    fi
    # Linux / WSL
    if command -v apt-get &>/dev/null; then echo "apt"
    elif command -v dnf &>/dev/null; then echo "dnf"
    elif command -v pacman &>/dev/null; then echo "pacman"
    elif command -v zypper &>/dev/null; then echo "zypper"
    else fail "Unsupported package manager. Install python3, python3-venv, and pipx manually."
    fi
}

# ── Install a system package if missing ──────
install_pkg() {
    local pkg="$1"
    local mgr="$2"
    warn "Installing ${pkg}..."
    case "$mgr" in
        apt)    sudo apt-get update -qq && sudo apt-get install -y -qq "$pkg" ;;
        dnf)    sudo dnf install -y -q "$pkg" ;;
        pacman) sudo pacman -S --noconfirm --needed "$pkg" ;;
        zypper) sudo zypper install -y "$pkg" ;;
        brew)   brew install "$pkg" ;;
    esac
}

# ── Ensure Python 3.9+ is available ─────────
ensure_python() {
    if command -v python3 &>/dev/null; then
        local ver
        ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        local major minor
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if (( major >= 3 && minor >= 9 )); then
            info "Python ${ver} found"
            return
        fi
        warn "Python ${ver} found but 3.9+ is required"
    fi
    install_pkg python3 "$PKG_MGR"
}

# ── Ensure python3-venv is available ─────────
ensure_venv() {
    if python3 -c "import venv" &>/dev/null; then
        info "python3-venv available"
        return
    fi
    case "$PKG_MGR" in
        apt)    install_pkg python3-venv "$PKG_MGR" ;;
        dnf)    install_pkg python3-libs "$PKG_MGR" ;;  # venv included
        pacman) info "venv is bundled with python on Arch" ;;
        zypper) install_pkg python3-venv "$PKG_MGR" ;;
        brew)   info "venv is bundled with python on macOS" ;;
    esac
}

# ── Ensure pipx is available ─────────────────
ensure_pipx() {
    if command -v pipx &>/dev/null; then
        info "pipx found at $(command -v pipx)"
        return
    fi
    case "$PKG_MGR" in
        apt)    install_pkg pipx "$PKG_MGR" ;;
        dnf)    install_pkg pipx "$PKG_MGR" ;;
        pacman) install_pkg python-pipx "$PKG_MGR" ;;
        zypper) install_pkg python3-pipx "$PKG_MGR" ;;
        brew)   install_pkg pipx "$PKG_MGR" ;;
    esac
    # Ensure ~/.local/bin is in PATH
    pipx ensurepath 2>/dev/null || true
}

# ── Ensure external dependencies ─────────────
ensure_external_deps() {
    local deps=("HandBrakeCLI" "mediainfo" "mkvpropedit")
    local missing=()
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done
    if (( ${#missing[@]} > 0 )); then
        warn "Optional runtime dependencies not found: ${missing[*]}"
        echo "  These are required at runtime. Install them separately:"
        echo "    HandBrakeCLI  → https://handbrake.fr/downloads2.php"
        echo "    mediainfo     → your package manager (mediainfo)"
        echo "    mkvpropedit   → your package manager (mkvtoolnix)"
    else
        info "Runtime dependencies found: ${deps[*]}"
    fi
}

# ── Main ─────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " convert-video installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

PKG_MGR=$(detect_pkg_manager)
info "Package manager: ${PKG_MGR}"

ensure_python
ensure_venv
ensure_pipx
echo

# ── Install convert-video ────────────────────
info "Installing convert-video via pipx..."
if pipx list 2>/dev/null | grep -q "convert-video"; then
    pipx reinstall "$SCRIPT_DIR"
else
    pipx install "$SCRIPT_DIR"
fi

echo
ensure_external_deps
echo
info "Installation complete! Run 'convert-video --help' to get started."
