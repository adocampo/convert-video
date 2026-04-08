import os
from importlib.metadata import PackageNotFoundError, version


APP_NAME = "clutch"
LEGACY_APP_NAME = "convert-video"
GITHUB_REPO = "adocampo/clutch"


def get_package_names() -> tuple[str, ...]:
    return APP_NAME, LEGACY_APP_NAME


def build_state_dir() -> str:
    state_home = os.environ.get("XDG_STATE_HOME")
    if not state_home:
        state_home = os.path.join(os.path.expanduser("~"), ".local", "state")

    branded_path = os.path.join(state_home, APP_NAME)
    legacy_path = os.path.join(state_home, LEGACY_APP_NAME)
    if os.path.isdir(branded_path) or not os.path.isdir(legacy_path):
        return branded_path
    return legacy_path


def get_version() -> str:
    """Return the installed package version, or 'unknown' if not found."""
    for package_name in get_package_names():
        try:
            return version(package_name)
        except PackageNotFoundError:
            continue
    return "unknown"


__version__ = get_version()
