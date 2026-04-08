#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# install.sh — Install convert-video via pipx
# Works on Linux, macOS, and WSL
# ──────────────────────────────────────────────

REPO_URL="https://github.com/adocampo/convert-video.git"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[✓] $*${RESET}"; }
warn()    { echo -e "${YELLOW}[!] $*${RESET}"; }
fail()    { echo -e "${RED}[✗] $*${RESET}" >&2; exit 1; }

CLEANUP_DIR=""
cleanup() { [[ -n "$CLEANUP_DIR" ]] && rm -rf "$CLEANUP_DIR"; }
trap cleanup EXIT

# Detect whether we are running from a local repo checkout or piped
if [[ -f "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR=""
fi

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

# ── Ensure git is available ───────────────────
ensure_git() {
    if command -v git &>/dev/null; then
        info "git found"
        return
    fi
    install_pkg git "$PKG_MGR"
}

# ── Resolve source directory ─────────────────
resolve_source() {
    # If running from a repo checkout that has pyproject.toml, use it
    if [[ -n "$SCRIPT_DIR" && -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
        SOURCE_DIR="$SCRIPT_DIR"
        info "Installing from local checkout: ${SOURCE_DIR}"
        return
    fi
    # Otherwise clone the repo to a temporary directory
    ensure_git
    CLEANUP_DIR=$(mktemp -d)
    info "Cloning ${REPO_URL} into temporary directory..."
    git clone --depth 1 "$REPO_URL" "$CLEANUP_DIR" >/dev/null 2>&1
    SOURCE_DIR="$CLEANUP_DIR"
    info "Cloned to ${SOURCE_DIR}"
}

resolve_source
echo

# ── Install convert-video ────────────────────
info "Installing convert-video via pipx..."
if pipx list 2>/dev/null | grep -q "convert-video"; then
    pipx reinstall "$SOURCE_DIR"
else
    pipx install "$SOURCE_DIR"
fi

echo
ensure_external_deps

# ── Install systemd user unit (Linux only) ───
install_systemd_unit() {
    local unit_src="${SOURCE_DIR}/convert-video.service"
    local unit_dir="${HOME}/.config/systemd/user"
    local unit_dst="${unit_dir}/convert-video.service"

    if [[ "$(uname -s)" != "Linux" ]]; then
        return
    fi
    if [[ ! -f "$unit_src" ]]; then
        warn "Systemd unit file not found in repo, skipping."
        return
    fi

    mkdir -p "$unit_dir"
    cp "$unit_src" "$unit_dst"
    info "Installed systemd unit to ${unit_dst}"

    if command -v systemctl &>/dev/null; then
        if systemctl --user daemon-reload &>/dev/null; then
            info "Reloaded systemd user daemon"
        else
            warn "Could not reload the systemd user daemon automatically."
        fi
        echo "  To enable and start the service:"
        echo "    systemctl --user enable --now convert-video.service"
        echo "  To check its status:"
        echo "    systemctl --user status convert-video.service"
    fi
}
install_systemd_unit

echo
info "Installation complete! Run 'convert-video --help' to get started."
