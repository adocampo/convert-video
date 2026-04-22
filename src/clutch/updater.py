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


def _build_install_source(target_version: str | None = None) -> str:
    """Return the pipx-compatible install source for the given version.

    When *target_version* is provided the tagged source archive is used,
    which avoids requiring ``git`` in the subprocess environment.
    Falls back to the ``git+https`` URL when no version is specified.
    """
    if target_version:
        return f"https://github.com/{GITHUB_REPO}/archive/refs/tags/v{target_version}.zip"
    return f"git+https://github.com/{GITHUB_REPO}.git"


def _windows_deferred_install(
    source: str,
    *,
    on_progress: "Callable[[str], None] | None" = None,
    restart_command: "list[str] | None" = None,
) -> None:
    """Spawn a detached helper script that upgrades clutch after this process exits.

    On Windows the running ``python.exe`` inside the pipx venv is locked by
    the OS, preventing ``pipx install --force`` from recreating the venv.
    This function writes a small ``.cmd`` helper, launches it fully detached,
    and returns immediately.  The caller **must** exit promptly so the helper
    can proceed.
    """
    import tempfile

    pid = os.getpid()
    restart_cmd = ""
    if restart_command:
        # Build a quoted command line for the restart
        parts = []
        for arg in restart_command:
            if " " in arg or '"' in arg:
                parts.append(f'"{arg}"')
            else:
                parts.append(arg)
        restart_cmd = 'start "" ' + " ".join(parts) + "\n"

    legacy_uninstall = ""
    if _pipx_package_installed(LEGACY_APP_NAME):
        legacy_uninstall = f'pipx uninstall {LEGACY_APP_NAME} 2>NUL\n'

    script = (
        "@echo off\n"
        "REM --- clutch deferred upgrade helper ---\n"
        ":WAIT\n"
        f'tasklist /fi "PID eq {pid}" 2>NUL | find /i "{pid}" >NUL\n'
        "if %ERRORLEVEL% equ 0 (\n"
        "    timeout /t 1 /nobreak >NUL\n"
        "    goto WAIT\n"
        ")\n"
        "REM Parent process exited, safe to upgrade\n"
        f"{legacy_uninstall}"
        f'pipx install "{source}" --force\n'
        f"{restart_cmd}"
        'del "%~f0"\n'
    )

    script_path = os.path.join(tempfile.gettempdir(), f"clutch-upgrade-{pid}.cmd")
    with open(script_path, "w") as fh:
        fh.write(script)

    if on_progress:
        on_progress("Launching deferred upgrade helper\u2026")

    # CREATE_NO_WINDOW so no visible terminal pops up.
    # CREATE_NEW_PROCESS_GROUP so it survives parent exit.
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        ["cmd", "/c", script_path],
        creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install_latest_version(
    *,
    target_version: str | None = None,
    on_progress: "Callable[[str], None] | None" = None,
) -> subprocess.CompletedProcess:
    """Install the latest clutch version from GitHub via pipx.

    When *target_version* is given the tagged source archive is downloaded
    directly (no ``git`` required).  If *on_progress* is provided it is
    called with each meaningful line from the pipx output so the caller can
    update the UI step label.
    """
    if _pipx_package_installed(LEGACY_APP_NAME):
        subprocess.run(
            ["pipx", "uninstall", LEGACY_APP_NAME],
            capture_output=False,
        )
    source = _build_install_source(target_version)
    proc = subprocess.Popen(
        ["pipx", "install", source, "--force"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_lines: list[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if line:
            output_lines.append(line)
            if on_progress:
                on_progress(line)
    returncode = proc.wait()
    return subprocess.CompletedProcess(
        proc.args, returncode, stdout="\n".join(output_lines), stderr="",
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

    # On Windows the running python.exe in the pipx venv is locked by the
    # current process, so pipx cannot recreate the venv.  Use a detached
    # helper script that waits for this process to die then runs pipx.
    if sys.platform == "win32":
        source = _build_install_source(remote_ver)
        _windows_deferred_install(source, on_progress=lambda line: print(f"  {line}"))
        info(
            f"Upgrade to {remote_ver} will complete in the background.\n"
            "  The current process must exit first so the installer can replace the environment."
        )
        sys.exit(0)

    result = install_latest_version(
        target_version=remote_ver,
        on_progress=lambda line: print(f"  {line}"),
    )
    if result.returncode == 0:
        mark_update_installed(remote_ver)
        info(f"Successfully upgraded to {remote_ver}.")
    else:
        if result.stdout:
            print(result.stdout)
        error("Upgrade failed. Check the output above for details.")
        sys.exit(1)
