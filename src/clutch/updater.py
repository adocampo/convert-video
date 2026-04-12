import base64
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone

from clutch import APP_NAME, GITHUB_REPO, LEGACY_APP_NAME, build_state_dir, get_version
from clutch.output import info, error

_UPDATE_STATE_LOCK = threading.Lock()


def build_update_state_path() -> str:
    """Return the shared state file used to cache update checks."""
    return os.path.join(build_state_dir(), "update-state.json")


def _local_today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_update_state(local_version: str | None = None) -> dict[str, object]:
    return {
        "checked_at": "",
        "checked_date": "",
        "cli_notice_date": "",
        "local_version": local_version or get_version(),
        "remote_version": "",
        "update_available": False,
        "changelog": "",
        "last_error": "",
    }


def _normalize_update_state(raw_state: object, local_version: str | None = None) -> dict[str, object]:
    current_version = local_version or get_version()
    state = _default_update_state(current_version)

    if isinstance(raw_state, dict):
        state["checked_at"] = str(raw_state.get("checked_at") or "")
        state["checked_date"] = str(raw_state.get("checked_date") or "")
        state["cli_notice_date"] = str(raw_state.get("cli_notice_date") or "")
        state["local_version"] = str(raw_state.get("local_version") or current_version)
        state["remote_version"] = str(raw_state.get("remote_version") or "")
        state["update_available"] = bool(raw_state.get("update_available", False))
        state["changelog"] = str(raw_state.get("changelog") or "")
        state["last_error"] = str(raw_state.get("last_error") or "")

    # Invalidate stale cached state after upgrading or downgrading locally.
    if state["local_version"] != current_version:
        return _default_update_state(current_version)

    if not state["remote_version"]:
        state["update_available"] = False
        state["changelog"] = ""

    if state["remote_version"] == current_version:
        state["update_available"] = False
        state["changelog"] = ""

    if not state["update_available"]:
        state["changelog"] = ""

    return state


def _read_update_state_unlocked() -> dict[str, object]:
    path = build_update_state_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        payload = {}
    return _normalize_update_state(payload)


def _write_update_state_unlocked(state: dict[str, object]) -> dict[str, object]:
    path = build_update_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized = _normalize_update_state(state, str(state.get("local_version") or get_version()))
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, indent=2, sort_keys=True)
    os.replace(temp_path, path)
    return normalized


def load_update_state() -> dict[str, object]:
    """Load the cached update state, normalizing it for the current version."""
    with _UPDATE_STATE_LOCK:
        return _read_update_state_unlocked()


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


def check_for_updates(*, quiet: bool = False) -> tuple[str, str | None, bool]:
    """Query GitHub for the latest release and compare with the local version."""
    local_ver = get_version()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        if not quiet:
            error(f"Could not reach GitHub: {exc}")
        return local_ver, None, False

    remote_ver = data.get("tag_name", "").lstrip("v")
    if not remote_ver:
        if not quiet:
            error("Could not determine the latest remote version.")
        return local_ver, None, False

    update_available = _parse_version_tuple(remote_ver) > _parse_version_tuple(local_ver)
    return local_ver, remote_ver, update_available


_UPDATE_STALE_SECONDS = 12 * 3600  # Re-check at least every 12 hours


def _checked_recently(state: dict[str, object]) -> bool:
    """Return True if the last check is recent enough to skip re-fetching."""
    checked_at = str(state.get("checked_at") or "")
    if not checked_at:
        return False
    try:
        ts = datetime.fromisoformat(checked_at)
    except (ValueError, TypeError):
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age < _UPDATE_STALE_SECONDS


def get_update_state(*, force: bool = False, quiet: bool = False) -> dict[str, object]:
    """Return cached release info, refreshing if the cache is stale."""
    with _UPDATE_STATE_LOCK:
        cached_state = _read_update_state_unlocked()
        if not force and _checked_recently(cached_state):
            return cached_state

        local_ver, remote_ver, update_available = check_for_updates(quiet=quiet)
        next_state = _normalize_update_state(cached_state, local_ver)
        next_state["checked_at"] = _utc_now()
        next_state["checked_date"] = _local_today()
        next_state["local_version"] = local_ver

        if remote_ver is None:
            next_state["last_error"] = "Could not reach GitHub."
            return _write_update_state_unlocked(next_state)

        next_state["remote_version"] = remote_ver
        next_state["update_available"] = update_available
        next_state["changelog"] = get_update_changelog(local_ver, remote_ver) if update_available else ""
        next_state["last_error"] = ""
        return _write_update_state_unlocked(next_state)


def mark_update_installed(installed_version: str | None = None) -> dict[str, object]:
    """Persist that the current version is installed and no update badge is needed."""
    local_ver = installed_version or get_version()
    state = _default_update_state(local_ver)
    state["checked_at"] = _utc_now()
    state["checked_date"] = _local_today()
    state["cli_notice_date"] = ""
    state["remote_version"] = local_ver
    with _UPDATE_STATE_LOCK:
        return _write_update_state_unlocked(state)


def mark_cli_notice_shown() -> dict[str, object]:
    """Persist that the daily CLI update hint has already been displayed."""
    with _UPDATE_STATE_LOCK:
        state = _read_update_state_unlocked()
        state["cli_notice_date"] = _local_today()
        return _write_update_state_unlocked(state)


def _pipx_package_installed(package_name: str) -> bool:
    result = subprocess.run(
        ["pipx", "list"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and package_name in result.stdout


def install_latest_version() -> subprocess.CompletedProcess:
    """Install the latest clutch version from GitHub via pipx."""
    if _pipx_package_installed(LEGACY_APP_NAME):
        subprocess.run(
            ["pipx", "uninstall", LEGACY_APP_NAME],
            capture_output=False,
        )
    return subprocess.run(
        ["pipx", "install", f"git+https://github.com/{GITHUB_REPO}.git", "--force"],
        capture_output=False,
    )


def get_update_changelog(current_ver: str, latest_ver: str) -> str:
    """Fetch the remote CHANGELOG and return the sections between two versions."""
    changelog = _fetch_remote_changelog()
    if not changelog:
        return ""
    return extract_changelog_between(changelog, current_ver, latest_ver)


def upgrade():
    """Upgrade clutch to the latest version via pipx."""
    local_ver, remote_ver, update_available = check_for_updates()
    if remote_ver is None:
        sys.exit(1)

    print(f"  Current version : {local_ver}")
    print(f"  Latest version  : {remote_ver}")

    if not update_available:
        info("Already up to date.")
        mark_update_installed(local_ver)
        sys.exit(0)

    print(f"\nUpgrading {APP_NAME} {local_ver} \u2192 {remote_ver} ...")
    result = install_latest_version()
    if result.returncode == 0:
        mark_update_installed(remote_ver)
        info(f"Successfully upgraded to {remote_ver}.")
    else:
        error("Upgrade failed. Check the output above for details.")
        sys.exit(1)
