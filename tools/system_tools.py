"""Bounded read-only system measurements, without shells or device identifiers."""

import platform
from pathlib import Path

import psutil

from config.settings import PROJECT_ROOT
from config.tool_settings import DEFAULT_RESULTS, MAX_RESULTS
from core.models import ExecutionResult, RiskLevel
from security.validator import ValidationError, validate_local_path
from tools._support import _limit, _metadata, _safe_result

GET_SYSTEM_INFO_METADATA = _metadata("system.get_system_info", "Read OS, architecture, and Python version.", RiskLevel.READ_ONLY)
GET_CPU_INFO_METADATA = _metadata("system.get_cpu_info", "Read physical and logical CPU counts; unknown counts are null.", RiskLevel.READ_ONLY)
GET_CPU_USAGE_METADATA = _metadata("system.get_cpu_usage", "Measure CPU utilization over a 0.1-second sample.", RiskLevel.READ_ONLY)
GET_MEMORY_INFO_METADATA = _metadata("system.get_memory_info", "Read physical memory availability in bytes.", RiskLevel.READ_ONLY)
GET_DISK_INFO_METADATA = _metadata("system.get_disk_info", "Read disk usage for a local path (project drive by default).", RiskLevel.READ_ONLY, {"path": {"type": "string", "minLength": 1}})
LIST_PROCESSES_METADATA = _metadata("system.list_processes", "Read a bounded PID/name process summary.", RiskLevel.READ_ONLY, {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "default": DEFAULT_RESULTS}})


@_safe_result
def get_system_info() -> ExecutionResult:
    return ExecutionResult(True, "System information retrieved.", {
        "os": platform.system(), "os_release": platform.release(),
        "os_version": platform.version(), "architecture": platform.machine(),
        "python_version": platform.python_version(),
    })


@_safe_result
def get_cpu_info() -> ExecutionResult:
    return ExecutionResult(True, "CPU information retrieved.", {
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cpus": psutil.cpu_count(logical=True),
    })


@_safe_result
def get_cpu_usage() -> ExecutionResult:
    return ExecutionResult(True, "CPU utilization sampled.", {
        "percent": psutil.cpu_percent(interval=0.1), "sample_seconds": 0.1,
    })


@_safe_result
def get_memory_info() -> ExecutionResult:
    memory = psutil.virtual_memory()
    return ExecutionResult(True, "Physical memory information retrieved.", {
        "total_bytes": memory.total, "available_bytes": memory.available,
        "used_bytes": memory.total - memory.available, "percent": memory.percent,
    })


@_safe_result
def get_disk_info(path: str | Path = PROJECT_ROOT) -> ExecutionResult:
    local = validate_local_path(path)
    disk = psutil.disk_usage(str(local if local.is_dir() else local.parent))
    return ExecutionResult(True, "Disk usage retrieved.", {
        "total_bytes": disk.total, "used_bytes": disk.used,
        "free_bytes": disk.free, "percent": disk.percent,
    })


@_safe_result
def list_processes(limit: int = DEFAULT_RESULTS) -> ExecutionResult:
    _limit(limit, MAX_RESULTS)
    rows = []
    skipped = 0
    examined = 0
    limited = False
    try:
        for process in psutil.process_iter(attrs=["pid", "name"], ad_value=None):
            examined += 1
            if len(rows) >= limit or examined > MAX_RESULTS * 2:
                limited = True
                break
            try:
                info = process.info
                if info["name"] is None:
                    skipped += 1
                    continue
                rows.append({"pid": info["pid"], "name": info["name"]})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                skipped += 1
    except psutil.Error:
        raise ValidationError("PROCESS_QUERY_FAILED") from None
    rows.sort(key=lambda row: row["pid"])
    return ExecutionResult(True, "Process summary retrieved.", {
        "processes": rows, "limit_reached": limited, "skipped": skipped,
    })
