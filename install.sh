#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# install.sh — Install clutch via pipx
# Works on Linux, macOS, and WSL
# ──────────────────────────────────────────────

REPO_URL="https://github.com/adocampo/clutch.git"
APP_NAME="clutch"
LEGACY_APP_NAME="convert-video"
SYSTEMD_UNIT_NAME="clutch.service"
LEGACY_SYSTEMD_UNIT_NAME="convert-video.service"

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
    elif command -v apk &>/dev/null; then echo "apk"
    elif command -v zypper &>/dev/null; then echo "zypper"
    else echo "unknown"
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
        apk)    sudo apk add --quiet "$pkg" ;;
        zypper) sudo zypper install -y "$pkg" ;;
        brew)   brew install "$pkg" ;;
        *)      warn "Cannot auto-install ${pkg} (unknown package manager). Install it manually."
                return 1 ;;
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
    case "$PKG_MGR" in
        apk) install_pkg python3 "$PKG_MGR" ;;
        *)   install_pkg python3 "$PKG_MGR" ;;
    esac
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
        apk)    info "venv is bundled with python on Alpine" ;;
        zypper) install_pkg python3-venv "$PKG_MGR" ;;
        brew)   info "venv is bundled with python on macOS" ;;
    esac
}

# ── Ensure pipx is available ─────────────────
ensure_pipx() {
    if command -v pipx &>/dev/null; then
        # Verify pipx actually works (Arch can break it after Python upgrades)
        if pipx --version &>/dev/null; then
            info "pipx found at $(command -v pipx)"
        else
            warn "pipx binary found but broken (likely a Python version mismatch). Reinstalling..."
            case "$PKG_MGR" in
                pacman) sudo pacman -S --noconfirm python-pipx ;;
                *)      install_pkg pipx "$PKG_MGR" ;;
            esac
        fi
    else
        case "$PKG_MGR" in
            apt)    install_pkg pipx "$PKG_MGR" ;;
            dnf)    install_pkg pipx "$PKG_MGR" ;;
            pacman) install_pkg python-pipx "$PKG_MGR" ;;
            apk)    install_pkg pipx "$PKG_MGR" ;;
            zypper) install_pkg python3-pipx "$PKG_MGR" ;;
            brew)   install_pkg pipx "$PKG_MGR" ;;
            *)      warn "Install pipx manually: https://pypa.github.io/pipx/"
                    fail "pipx is required to install ${APP_NAME}." ;;
        esac
    fi
    # Ensure ~/.local/bin is in PATH for this session and future shells
    pipx ensurepath 2>/dev/null || true
    if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
        export PATH="${HOME}/.local/bin:${PATH}"
    fi
}

# ── Ensure external dependencies ─────────────
# Maps: binary name -> package name per distro
# HandBrakeCLI is only in Flatpak/AUR/manual on most distros; we handle it specially.
install_runtime_dep() {
    local binary="$1"
    case "$binary" in
        HandBrakeCLI)
            case "$PKG_MGR" in
                apt)    install_pkg handbrake-cli "$PKG_MGR" ;;
                dnf)    install_pkg HandBrake-cli "$PKG_MGR" ;;
                pacman) install_pkg handbrake-cli "$PKG_MGR" ;;
                apk)    install_pkg handbrake "$PKG_MGR" ;;
                brew)   brew install --cask handbrake ;;
                *)      return 1 ;;
            esac
            ;;
        mediainfo)
            case "$PKG_MGR" in
                apt)    install_pkg mediainfo "$PKG_MGR" ;;
                dnf)    install_pkg mediainfo "$PKG_MGR" ;;
                pacman) install_pkg mediainfo "$PKG_MGR" ;;
                apk)    install_pkg mediainfo "$PKG_MGR" ;;
                brew)   install_pkg media-info "$PKG_MGR" ;;
                *)      return 1 ;;
            esac
            ;;
        mkvpropedit|mkvmerge)
            # Both come from the mkvtoolnix package
            case "$PKG_MGR" in
                apt)    install_pkg mkvtoolnix "$PKG_MGR" ;;
                dnf)    install_pkg mkvtoolnix "$PKG_MGR" ;;
                pacman) install_pkg mkvtoolnix-cli "$PKG_MGR" ;;
                apk)    install_pkg mkvtoolnix "$PKG_MGR" ;;
                brew)   install_pkg mkvtoolnix "$PKG_MGR" ;;
                *)      return 1 ;;
            esac
            ;;
    esac
}

ensure_external_deps() {
    local deps=("HandBrakeCLI" "mediainfo" "mkvpropedit" "mkvmerge")
    local missing=()
    local still_missing=()

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done

    if (( ${#missing[@]} == 0 )); then
        info "Runtime dependencies found: ${deps[*]}"
        return
    fi

    # Track which packages we already tried to avoid duplicate installs
    # (mkvpropedit and mkvmerge come from the same package)
    local tried_mkvtoolnix=false
    for dep in "${missing[@]}"; do
        if [[ "$dep" == "mkvmerge" || "$dep" == "mkvpropedit" ]] && $tried_mkvtoolnix; then
            continue
        fi
        if [[ "$dep" == "mkvmerge" || "$dep" == "mkvpropedit" ]]; then
            tried_mkvtoolnix=true
        fi
        install_runtime_dep "$dep" || true
    done

    # Re-check after install attempts
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &>/dev/null; then
            still_missing+=("$dep")
        fi
    done

    if (( ${#still_missing[@]} > 0 )); then
        warn "Could not auto-install: ${still_missing[*]}"
        echo "  Install them manually or configure their paths in the clutch dashboard"
        echo "  under Settings > Binary Paths."
        echo "    HandBrakeCLI  -> https://handbrake.fr/downloads2.php"
        echo "    mediainfo     -> your package manager (mediainfo)"
        echo "    mkvpropedit   -> your package manager (mkvtoolnix)"
        echo "    mkvmerge      -> your package manager (mkvtoolnix)"
    else
        info "Runtime dependencies installed: ${deps[*]}"
    fi
}

# ── Main ─────────────────────────────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " clutch installer"
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

pipx_has_package() {
    local package_name="$1"
    pipx list 2>/dev/null | grep -q "$package_name"
}

# ── Install clutch ───────────────────────────
info "Installing ${APP_NAME} via pipx..."
if pipx_has_package "$LEGACY_APP_NAME"; then
    info "Legacy pipx installation detected; replacing it with ${APP_NAME} from ${SOURCE_DIR}"
    pipx uninstall "$LEGACY_APP_NAME" >/dev/null
fi

if pipx_has_package "$APP_NAME"; then
    info "Existing ${APP_NAME} pipx installation detected; reinstalling from ${SOURCE_DIR}"
    pipx uninstall "$APP_NAME" >/dev/null
fi

pipx install "$SOURCE_DIR"

echo
ensure_external_deps

# ── Install systemd user unit (Linux only) ───
install_systemd_unit() {
    local unit_src="${SOURCE_DIR}/${SYSTEMD_UNIT_NAME}"
    local unit_dir="${HOME}/.config/systemd/user"
    local unit_dst="${unit_dir}/${SYSTEMD_UNIT_NAME}"
    local legacy_unit_dst="${unit_dir}/${LEGACY_SYSTEMD_UNIT_NAME}"

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
    if [[ -f "$legacy_unit_dst" ]]; then
        rm -f "$legacy_unit_dst"
        info "Removed legacy systemd unit ${legacy_unit_dst}"
    fi

    if command -v systemctl &>/dev/null; then
        if systemctl --user daemon-reload &>/dev/null; then
            info "Reloaded systemd user daemon"
        else
            warn "Could not reload the systemd user daemon automatically."
        fi
        echo "  To enable and start the service:"
        echo "    systemctl --user enable --now ${SYSTEMD_UNIT_NAME}"
        echo "  To check its status:"
        echo "    systemctl --user status ${SYSTEMD_UNIT_NAME}"
    fi
}
install_systemd_unit

echo
info "Installation complete! Run '${APP_NAME} --help' to get started."
