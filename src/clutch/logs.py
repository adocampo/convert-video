from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _list_log_files() -> List[Dict[str, object]]:
    """Return available log files sorted newest-first."""
    from clutch.output import get_log_dir
    log_dir = get_log_dir()
    if not log_dir or not os.path.isdir(log_dir):
        return []
    result = []
    for name in sorted(os.listdir(log_dir), reverse=True):
        if not name.startswith("clutch.log"):
            continue
        full = os.path.join(log_dir, name)
        try:
            st = os.stat(full)
        except OSError:
            continue
        result.append({
            "name": name,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return result


def _download_log_file(filename: str) -> Optional[bytes]:
    """Return the raw bytes of a log file, or None if not found."""
    from clutch.output import get_log_dir
    log_dir = get_log_dir()
    if not log_dir:
        return None
    safe = os.path.basename(filename)
    if not safe.startswith("clutch.log"):
        return None
    target = os.path.join(log_dir, safe)
    if not os.path.isfile(target):
        return None
    try:
        with open(target, "rb") as f:
            return f.read()
    except OSError:
        return None


def _delete_log_file(filename: str) -> bool:
    """Delete a single rotated log file. Refuses to delete the active log."""
    from clutch.output import get_log_dir
    log_dir = get_log_dir()
    if not log_dir:
        return False
    safe = os.path.basename(filename)
    if not safe.startswith("clutch.log") or safe == "clutch.log":
        return False
    target = os.path.join(log_dir, safe)
    if not os.path.isfile(target):
        return False
    try:
        os.remove(target)
        return True
    except OSError:
        return False


def _clear_old_log_files() -> int:
    """Delete all rotated log files (keeps the active clutch.log)."""
    from clutch.output import get_log_dir
    log_dir = get_log_dir()
    if not log_dir or not os.path.isdir(log_dir):
        return 0
    count = 0
    for name in os.listdir(log_dir):
        if name.startswith("clutch.log."):
            try:
                os.remove(os.path.join(log_dir, name))
                count += 1
            except OSError:
                pass
    return count


def _read_log_entries(
    *,
    filename: str = "",
    level: str = "",
    search: str = "",
    page: int = 1,
    limit: int = 200,
) -> Dict[str, object]:
    """Read and filter log entries from the active (or specified) log file."""
    from clutch.output import get_log_dir
    log_dir = get_log_dir()
    if not log_dir:
        return {"entries": [], "total": 0, "page": page, "limit": limit}

    if filename:
        # Prevent path traversal
        safe = os.path.basename(filename)
        target = os.path.join(log_dir, safe)
    else:
        target = os.path.join(log_dir, "clutch.log")

    if not os.path.isfile(target):
        return {"entries": [], "total": 0, "page": page, "limit": limit}

    entries: List[Dict[str, str]] = []
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    exact_level = level.upper() if level else ""
    search_lower = search.lower()

    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                # Expected format: 2026-04-14T12:34:56 [INFO ] clutch: message
                parts = line.split(" ", 3)
                if len(parts) < 4:
                    entry_level = "INFO"
                    entry_ts = ""
                    entry_source = ""
                    entry_msg = line
                else:
                    entry_ts = parts[0]
                    bracket = parts[1].strip("[]").strip()
                    entry_level = bracket if bracket in valid_levels else "INFO"
                    entry_source = parts[2].rstrip(":")
                    entry_msg = parts[3] if len(parts) > 3 else ""

                if exact_level and entry_level != exact_level:
                    continue
                if search_lower and search_lower not in line.lower():
                    continue

                entries.append({
                    "timestamp": entry_ts,
                    "level": entry_level,
                    "source": entry_source,
                    "message": entry_msg,
                })
    except OSError:
        return {"entries": [], "total": 0, "page": page, "limit": limit}

    total = len(entries)
    # Return entries in reverse chronological order (newest first), paginated
    entries.reverse()
    start = (page - 1) * limit
    page_entries = entries[start:start + limit]
    return {"entries": page_entries, "total": total, "page": page, "limit": limit}


def _collect_system_stats() -> Dict[str, object]:
    """Collect system resource statistics without external dependencies."""
    stats: Dict[str, object] = {}

    # ── CPU ──
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        total = sum(int(p) for p in parts[1:])
        idle = int(parts[4])
        stats["cpu"] = {"total": total, "idle": idle}
    except (OSError, ValueError, IndexError):
        stats["cpu"] = None

    try:
        load1, load5, load15 = os.getloadavg()
        stats["load"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except (OSError, AttributeError):
        stats["load"] = None

    try:
        cpu_count = os.cpu_count() or 0
        stats["cpu_count"] = cpu_count
    except Exception:
        stats["cpu_count"] = None

    # CPU temperature (thermal zones)
    cpu_temp: Optional[float] = None
    try:
        import glob
        for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*/")):
            try:
                with open(os.path.join(zone, "type")) as f:
                    ztype = f.read().strip().lower()
                if "cpu" not in ztype and "x86" not in ztype and "core" not in ztype and "soc" not in ztype:
                    continue
                with open(os.path.join(zone, "temp")) as f:
                    cpu_temp = int(f.read().strip()) / 1000.0
                break
            except (OSError, ValueError):
                continue
        if cpu_temp is None:
            for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*/")):
                try:
                    with open(os.path.join(zone, "temp")) as f:
                        cpu_temp = int(f.read().strip()) / 1000.0
                    break
                except (OSError, ValueError):
                    continue
    except Exception:
        pass
    stats["cpu_temp"] = round(cpu_temp, 1) if cpu_temp is not None else None

    # ── Memory ──
    try:
        mem: Dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    mem[key] = int(parts[1]) * 1024  # kB → bytes
        total_mem = mem.get("MemTotal", 0)
        avail_mem = mem.get("MemAvailable", 0)
        stats["memory"] = {
            "total": total_mem,
            "available": avail_mem,
            "used": total_mem - avail_mem,
        }
    except (OSError, ValueError):
        # Fallback for Windows / non-Linux: use ctypes or wmic
        if os.name == "nt":
            try:
                import ctypes
                class _MEMSTAT(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong),
                                ("dwMemoryLoad", ctypes.c_ulong),
                                ("ullTotalPhys", ctypes.c_ulonglong),
                                ("ullAvailPhys", ctypes.c_ulonglong),
                                ("ullTotalPageFile", ctypes.c_ulonglong),
                                ("ullAvailPageFile", ctypes.c_ulonglong),
                                ("ullTotalVirtual", ctypes.c_ulonglong),
                                ("ullAvailVirtual", ctypes.c_ulonglong),
                                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
                ms = _MEMSTAT()
                ms.dwLength = ctypes.sizeof(ms)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
                stats["memory"] = {
                    "total": ms.ullTotalPhys,
                    "available": ms.ullAvailPhys,
                    "used": ms.ullTotalPhys - ms.ullAvailPhys,
                }
            except Exception:
                stats["memory"] = None
        else:
            stats["memory"] = None

    # ── Disks (mount points) ──
    disks: List[Dict[str, object]] = []
    seen_devs: set = set()
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                device, mount = parts[0], parts[1]
                if not device.startswith("/") or device in seen_devs:
                    continue
                seen_devs.add(device)
                try:
                    usage = shutil.disk_usage(mount)
                    disks.append({
                        "mount": mount,
                        "device": device,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                    })
                except OSError:
                    continue
    except OSError:
        # Fallback for Windows: use GetLogicalDrives bitmask + net use for UNC
        if os.name == "nt":
            import ctypes
            import string

            DRIVE_REMOVABLE = 2
            DRIVE_CDROM = 5
            GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW

            # Build drive-letter → UNC mapping from 'net use'
            drive_to_unc: dict = {}
            unmapped_uncs: list = []
            try:
                result = subprocess.run(
                    ["net", "use"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    local = None
                    remote = None
                    for part in parts:
                        if len(part) == 2 and part[1] == ":" and part[0].isalpha():
                            local = part.upper()
                        if part.startswith("\\\\"):
                            remote = part
                    if remote:
                        if local:
                            drive_to_unc[local] = remote
                        else:
                            unmapped_uncs.append(remote)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            mapped_uncs = set(drive_to_unc.values())

            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(string.ascii_uppercase):
                if not (bitmask & (1 << i)):
                    continue
                drive = f"{letter}:\\"
                dtype = GetDriveTypeW(drive)
                key = f"{letter}:"
                unc = drive_to_unc.get(key)
                label = f"{drive} ({unc})" if unc else drive
                try:
                    usage = shutil.disk_usage(drive)
                    disks.append({
                        "mount": label,
                        "device": label,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                    })
                except OSError:
                    # Skip removable / CD-ROM drives with no media
                    if dtype in (DRIVE_REMOVABLE, DRIVE_CDROM):
                        continue
                    disks.append({
                        "mount": label,
                        "device": label,
                        "total": None,
                        "used": None,
                        "free": None,
                    })

            # Include UNC network shares not already mapped to a drive letter
            for unc in unmapped_uncs:
                if unc in mapped_uncs:
                    continue
                try:
                    usage = shutil.disk_usage(unc)
                    disks.append({
                        "mount": unc,
                        "device": unc,
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free,
                    })
                except OSError:
                    disks.append({
                        "mount": unc,
                        "device": unc,
                        "total": None,
                        "used": None,
                        "free": None,
                    })
    stats["disks"] = disks

    # ── GPUs (nvidia-smi) ──
    gpus: List[Dict[str, object]] = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,fan.speed",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, check=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            cols = [c.strip() for c in line.split(",")]
            if len(cols) < 4:
                continue
            try:
                idx = int(cols[0])
            except ValueError:
                continue
            name = cols[1].removeprefix("NVIDIA ") if len(cols) > 1 else "Unknown"

            def safe_int(v: str) -> Optional[int]:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return None

            gpus.append({
                "index": idx,
                "name": name,
                "mem_total_mib": safe_int(cols[2]),
                "mem_used_mib": safe_int(cols[3]),
                "utilization_pct": safe_int(cols[4]) if len(cols) > 4 else None,
                "temp_c": safe_int(cols[5]) if len(cols) > 5 else None,
                "fan_pct": safe_int(cols[6]) if len(cols) > 6 else None,
            })
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    stats["gpus"] = gpus

    return stats

