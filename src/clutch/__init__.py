import os
import shutil
from importlib.metadata import PackageNotFoundError, version


APP_NAME = "clutch"
LEGACY_APP_NAME = "convert-video"
GITHUB_REPO = "adocampo/clutch"

# ── Binary path registry ──
# Required external tools.  The key is the canonical binary name; the value
# stored at runtime is the resolved absolute path (or the bare name when no
# explicit configuration exists).
REQUIRED_BINARIES = ("HandBrakeCLI", "mediainfo", "mkvpropedit", "mkvmerge")

_binary_paths: dict[str, str] = {}


def get_binary_path(name: str) -> str:
    """Return the configured/detected path for *name*, or the bare name."""
    return _binary_paths.get(name) or name


def set_binary_paths(paths: dict[str, str]) -> None:
    """Bulk-set binary paths (called once at service startup)."""
    _binary_paths.update({k: v for k, v in paths.items() if v})


def detect_binary(name: str) -> str:
    """Try to locate *name* in ``$PATH``; return the path or ``""``."""
    return shutil.which(name) or ""


def detect_all_binaries() -> dict[str, str]:
    """Auto-detect every required binary and return ``{name: path}``."""
    return {name: detect_binary(name) for name in REQUIRED_BINARIES}


def get_missing_binaries() -> list[str]:
    """Return binary names that have no configured or detectable path."""
    return [name for name in REQUIRED_BINARIES if not _binary_paths.get(name)]


def get_package_names() -> tuple[str, ...]:
    return APP_NAME, LEGACY_APP_NAME


def _migrate_legacy_state_dir(legacy_path: str, branded_path: str):
    if not os.path.isdir(legacy_path):
        return

    os.makedirs(branded_path, exist_ok=True)

    try:
        with os.scandir(legacy_path) as entries:
            for entry in entries:
                target_path = os.path.join(branded_path, entry.name)
                if os.path.exists(target_path):
                    continue
                try:
                    shutil.move(entry.path, target_path)
                except OSError:
                    continue
    except OSError:
        return

    try:
        os.rmdir(legacy_path)
    except OSError:
        pass


def build_state_dir() -> str:
    explicit_state_dir = os.environ.get("CLUTCH_STATE_DIR")
    if explicit_state_dir:
        return explicit_state_dir

    state_home = os.environ.get("XDG_STATE_HOME")
    if not state_home:
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")

    branded_path = os.path.join(state_home, APP_NAME)
    legacy_path = os.path.join(state_home, LEGACY_APP_NAME)
    _migrate_legacy_state_dir(legacy_path, branded_path)
    return branded_path


def get_version() -> str:
    """Return the installed package version, or 'unknown' if not found."""
    for package_name in get_package_names():
        try:
            return version(package_name)
        except PackageNotFoundError:
            continue
    return "unknown"


__version__ = get_version()
