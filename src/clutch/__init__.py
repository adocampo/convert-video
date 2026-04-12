import os
import shutil
from importlib.metadata import PackageNotFoundError, version


APP_NAME = "clutch"
LEGACY_APP_NAME = "convert-video"
GITHUB_REPO = "adocampo/clutch"


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
