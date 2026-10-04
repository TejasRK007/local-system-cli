"""
System and process inspection tools for Milestone 7.

Provides controlled, read-only system and process inspection across Windows, macOS,
and Linux. Adheres strictly to the safety policy: read-only introspection without
arbitrary shell access or destructive capabilities.
"""

from __future__ import annotations

import os
import platform
import shutil
from typing import Any, Optional

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def get_system_info() -> dict[str, Any]:
    """
    Retrieve structured system hardware, OS, and resource utilization metrics.

    Returns:
        dict: High-level system statistics (OS, CPU count, RAM, Disk).
    """
    uname = platform.uname()

    # Memory inspection
    total_ram_gb = 0.0
    available_ram_gb = 0.0
    ram_percent = 0.0
    if psutil is not None:
        try:
            mem = psutil.virtual_memory()
            total_ram_gb = round(mem.total / (1024**3), 2)
            available_ram_gb = round(mem.available / (1024**3), 2)
            ram_percent = mem.percent
        except Exception:
            pass

    # Disk usage for current drive / root
    disk_total_gb = 0.0
    disk_used_gb = 0.0
    disk_free_gb = 0.0
    disk_percent = 0.0
    try:
        root_path = os.path.abspath(os.sep)
        disk = shutil.disk_usage(root_path)
        disk_total_gb = round(disk.total / (1024**3), 2)
        disk_used_gb = round(disk.used / (1024**3), 2)
        disk_free_gb = round(disk.free / (1024**3), 2)
        if disk.total > 0:
            disk_percent = round((disk.used / disk.total) * 100, 1)
    except Exception:
        pass

    return {
        "os": uname.system,
        "release": uname.release,
        "version": uname.version,
        "architecture": uname.machine,
        "processor": uname.processor or platform.processor(),
        "cpu_count": os.cpu_count() or 1,
        "ram_total_gb": total_ram_gb,
        "ram_available_gb": available_ram_gb,
        "ram_percent": ram_percent,
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_free_gb": disk_free_gb,
        "disk_percent": disk_percent,
    }


def list_processes(
    limit: int = 15,
    sort_by: str = "memory",
    name_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    List running processes safely with memory and CPU usage.

    Args:
        limit: Maximum number of processes to return.
        sort_by: "memory" or "cpu" sorting priority.
        name_filter: Optional substring to filter process names.

    Returns:
        list of process records: pid, name, memory_mb, memory_percent, cpu_percent, status.
    """
    if psutil is None:
        return []

    processes = []
    for proc in psutil.process_iter(
        ["pid", "name", "memory_info", "memory_percent", "cpu_percent", "status"]
    ):
        try:
            pinfo = proc.info
            name = pinfo.get("name") or "unknown"
            if name_filter and name_filter.lower() not in name.lower():
                continue

            mem_info = pinfo.get("memory_info")
            mem_rss = mem_info.rss if mem_info else 0
            mem_mb = round(mem_rss / (1024**2), 2)
            mem_percent = round(pinfo.get("memory_percent") or 0.0, 2)
            cpu_percent = round(pinfo.get("cpu_percent") or 0.0, 1)

            processes.append(
                {
                    "pid": pinfo.get("pid"),
                    "name": name,
                    "memory_mb": mem_mb,
                    "memory_percent": mem_percent,
                    "cpu_percent": cpu_percent,
                    "status": pinfo.get("status") or "running",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    sort_key = "memory_mb" if sort_by == "memory" else "cpu_percent"
    processes.sort(key=lambda x: x.get(sort_key, 0), reverse=True)
    return processes[:limit]


def find_process(query: str) -> list[dict[str, Any]]:
    """Search for processes matching a name or PID."""
    if query.isdigit():
        pid_target = int(query)
        if psutil is not None:
            try:
                proc = psutil.Process(pid_target)
                mem_info = proc.memory_info()
                return [
                    {
                        "pid": proc.pid,
                        "name": proc.name(),
                        "memory_mb": round(mem_info.rss / (1024**2), 2),
                        "memory_percent": round(proc.memory_percent(), 2),
                        "cpu_percent": round(proc.cpu_percent(), 1),
                        "status": proc.status(),
                    }
                ]
            except Exception:
                return []
    return list_processes(limit=20, name_filter=query)
