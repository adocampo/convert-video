import base64
import json
import re
import subprocess
import sys
import urllib.request
import urllib.error

from convert_video import get_version
from convert_video.output import info, warning, error

GITHUB_REPO = "adocampo/convert-video"


def _parse_version_tuple(version: str) -> tuple:
    """Convert a version string like '1.2.0' into a comparable tuple of ints."""
    try:
        return tuple(int(part) for part in version.split("."))
    except (ValueError, AttributeError):
        return (0,)


def _fetch_remote_changelog() -> str:
    """Fetch CHANGELOG.md from the default branch on GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/CHANGELOG.md"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return ""
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64" and content:
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return ""


def extract_changelog_between(changelog: str, current_ver: str, latest_ver: str) -> str:
    """Extract changelog sections for versions after current_ver up to latest_ver.

    Returns the combined markdown text for all intermediate versions, or an
    empty string if nothing could be extracted.
    """
    current_tuple = _parse_version_tuple(current_ver)
    latest_tuple = _parse_version_tuple(latest_ver)

    # Split into version sections on lines that start with "## ["
    section_pattern = re.compile(r"^## \[(.+?)\]", re.MULTILINE)
    matches = list(section_pattern.finditer(changelog))
    if not matches:
        return ""

    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        ver_str = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(changelog)
        sections.append((ver_str, changelog[start:end].rstrip()))

    result_parts: list[str] = []
    for ver_str, body in sections:
        ver_tuple = _parse_version_tuple(ver_str)
        # Include versions that are > current and <= latest
        if ver_tuple > current_tuple and ver_tuple <= latest_tuple:
            result_parts.append(body)

    return "\n\n".join(result_parts)


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


def get_update_changelog(current_ver: str, latest_ver: str) -> str:
    """Fetch the remote CHANGELOG and return the sections between two versions."""
    changelog = _fetch_remote_changelog()
    if not changelog:
        return ""
    return extract_changelog_between(changelog, current_ver, latest_ver)


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
