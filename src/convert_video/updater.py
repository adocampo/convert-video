import json
import subprocess
import sys
import urllib.request
import urllib.error

from convert_video import get_version
from convert_video.output import info, error

GITHUB_REPO = "adocampo/convert-video"


def check_for_updates() -> tuple:
    """Query GitHub for the latest release and compare with local version.

    Returns (local_version, remote_version, update_available).
    """
    local_ver = get_version()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        error(f"Could not reach GitHub: {exc}")
        return local_ver, None, False

    remote_ver = data.get("tag_name", "").lstrip("v")
    if not remote_ver:
        error("Could not determine the latest remote version.")
        return local_ver, None, False

    update_available = remote_ver != local_ver
    return local_ver, remote_ver, update_available


def upgrade():
    """Upgrade convert-video to the latest version via pipx."""
    local_ver, remote_ver, update_available = check_for_updates()
    if remote_ver is None:
        sys.exit(1)

    print(f"  Current version : {local_ver}")
    print(f"  Latest version  : {remote_ver}")

    if not update_available:
        info("Already up to date.")
        sys.exit(0)

    print(f"\nUpgrading convert-video {local_ver} \u2192 {remote_ver} ...")
    result = subprocess.run(
        ["pipx", "install", f"git+https://github.com/{GITHUB_REPO}.git", "--force"],
        capture_output=False,
    )
    if result.returncode == 0:
        info(f"Successfully upgraded to {remote_ver}.")
    else:
        error("Upgrade failed. Check the output above for details.")
        sys.exit(1)
