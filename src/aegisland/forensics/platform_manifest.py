"""Static OS/package metadata only. Never import drivers or probe devices."""

from __future__ import annotations

import html
import importlib.metadata
import platform
import shutil
from pathlib import Path

from .scope import geometry_boundary

ENVIRONMENTS = {"desktop", "jetson_orin_nano", "replay", "sitl", "unknown"}


def platform_manifest(
    declared: str = "replay",
    *,
    machine: str | None = None,
    system: str | None = None,
    device_model: str | None = None,
) -> dict:
    if not isinstance(declared, str) or declared not in ENVIRONMENTS:
        raise ValueError("Unsupported environment declaration")
    machine = machine if machine is not None else platform.machine()
    system = system if system is not None else platform.system()
    # No device-tree reads; an optional model is an explicit unverified declaration.
    kind = "unknown"
    if machine.lower() in {"x86_64", "amd64"}:
        kind = "desktop"
    elif (
        machine.lower() in {"aarch64", "arm64"}
        and device_model
        and "orin nano" in device_model.lower()
    ):
        kind = "jetson_orin_nano"
    consistent = not (declared == "jetson_orin_nano" and kind != "jetson_orin_nano")
    return {
        "schema_version": 1,
        "executed": False,
        "authority": "NONE",
        "execution_context": "replay",
        "declared_environment": declared,
        "host": {
            "machine": machine,
            "system": system,
            "device_model": device_model,
            "classification": kind,
            "knowledge": "inferred" if kind != "unknown" else "unknown",
            "scope": "OS architecture and optional model declaration; not device attestation",
        },
        "declaration_consistent": consistent,
        "measured_validation": {name: False for name in ("orin", "oak", "px4", "sitl", "flight")},
        "dependency_audit": "provisional_pending_final_exit_0",
    }


def _package(name: str) -> dict:
    try:
        version = importlib.metadata.version(name)
        return {"knowledge": "observed", "installed_metadata": True, "version": version}
    except importlib.metadata.PackageNotFoundError:
        return {"knowledge": "observed", "installed_metadata": False, "version": None}


def preflight(storage_root: Path, declared: str = "replay") -> dict:
    """No device nodes, driver imports, subprocesses, tests of write access or network."""
    checks = {
        "cuda": {
            "knowledge": "unknown",
            "runtime_available": None,
            "packages": {name: _package(name) for name in ("cuda-python", "torch", "cupy")},
            "detail": "Package metadata only; CUDA driver/context/kernels are not tested.",
        },
        "depthai": {
            "knowledge": "unknown",
            "device_available": None,
            "package": _package("depthai"),
            "detail": "No DepthAI import, enumeration, USB access or firmware boot.",
        },
        "px4_interfaces": {
            "knowledge": "unknown",
            "connected": None,
            "packages": {name: _package(name) for name in ("pyulog", "mavsdk", "pymavlink")},
            "detail": "No network, serial or PX4 commands; PyULog is file decoding only.",
        },
    }
    existing = storage_root.resolve()
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    try:
        usage = shutil.disk_usage(existing)
        checks["storage"] = {
            "knowledge": "observed",
            "path": str(existing),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "writable": None,
            "detail": "statvfs metadata; no write probe.",
        }
    except OSError as error:
        checks["storage"] = {"knowledge": "unknown", "detail": str(error)}
    checks["memory"] = {
        "knowledge": "unknown",
        "available_bytes": None,
        "detail": "No allocation benchmark or device-memory probe.",
    }
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(value.strip().split()[0]) * 1024
        if "MemAvailable" in values:
            checks["memory"].update(
                knowledge="observed",
                available_bytes=values["MemAvailable"],
                total_bytes=values.get("MemTotal"),
                detail="Kernel memory accounting snapshot; no workload measurement.",
            )
    except (OSError, ValueError):
        pass
    checks["expected_permissions"] = {
        "knowledge": "unknown",
        "verified": False,
        "requirements": [
            "OAK USB: site-reviewed udev rule for the actual device; do not chmod all USB nodes.",
            "PX4 recordings: read access to copied logs. No live serial/UDP connection is needed.",
            "VL53L1X recordings: read access to copied measurements. No I2C/GPIO opening is needed.",
            "Jetson/CUDA: administrator-reviewed GPU device permissions remain untested.",
        ],
        "detail": "No /dev inspection, opening, group modification or permission changes.",
    }
    return {
        "schema_version": 1,
        "purpose": "no_hardware_preflight",
        "executed": False,
        "authority": "NONE",
        "authority_change": "NONE",
        "geometry": geometry_boundary(),
        "platform": platform_manifest(declared),
        "checks": checks,
        "hardware_readiness": "unknown",
        "conclusion": {
            "knowledge": "unknown",
            "detail": "Static metadata cannot establish "
            "device readiness, Orin performance, SITL or flight validation.",
        },
    }


def preflight_reports(summary: dict) -> dict[str, bytes]:
    from .recorder import json_bytes

    text = json_bytes(summary).decode()
    markdown = (
        "# No-hardware preflight\n\nexecuted=False; authority=NONE.\n\n```json\n" + text + "```\n"
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
        "<title>No-hardware preflight</title><h1>No-hardware preflight</h1>"
        "<p>executed=False · authority=NONE · Hardware readiness unknown.</p><pre>"
        + html.escape(text)
        + "</pre></html>"
    )
    return {"report.html": page.encode(), "findings.md": markdown.encode()}
