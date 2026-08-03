"""Shared device/task compatibility rules for automatic and manual dispatch."""

from __future__ import annotations

from app.models.models import Device, Task


PROCESS_CAPABILITY_ALIASES: dict[str, set[str]] = {
    "site_prep": {"ground_leveling"},
    "pit_excavation": {"excavation"},
    "spoil_export": {"material_transport"},
    "precast_hoisting": {"lifting", "hoisting", "material_placement"},
    "vertical_transport": {"lifting", "hoisting"},
    "waste_removal": {"material_transport"},
    "safety_inspect": {"patrol_inspection", "environment_monitor"},
    "edge_guard": {"patrol_inspection"},
    "emergency_supply": {"material_transport"},
}
DEVICE_TYPE_ALIASES: dict[str, set[str]] = {
    "inspect": {"inspect", "inspection"},
    "inspection": {"inspect", "inspection"},
}
PROCESS_DEVICE_TYPES: dict[str, str] = {
    "site_prep": "excavator", "pit_excavation": "excavator", "spoil_export": "agv",
    "pile_foundation": "excavator", "material_transport": "agv", "waste_removal": "agv",
    "precast_hoisting": "crane", "vertical_transport": "crane", "masonry_wall": "masonry",
    "tile_paving": "masonry", "plastering": "masonry", "safety_inspect": "inspect",
    "edge_guard": "inspect", "surveying": "inspect", "quality_check": "inspect",
}


def capability_codes_for(code: str) -> set[str]:
    """Return an explicit capability code plus its documented compatible aliases."""

    codes = {code}
    codes.update(PROCESS_CAPABILITY_ALIASES.get(code, set()))
    for process_id, aliases in PROCESS_CAPABILITY_ALIASES.items():
        if code in aliases:
            codes.add(process_id)
            codes.update(aliases)
    return codes


def capability_codes_match(required_code: str, declared_code: str) -> bool:
    return bool(capability_codes_for(required_code).intersection(capability_codes_for(declared_code)))


def _device_type_is_allowed(device_type: str, allowed_types: list[str]) -> bool:
    return any(device_type in DEVICE_TYPE_ALIASES.get(allowed_type, {allowed_type}) for allowed_type in allowed_types)


def device_is_compatible(
    task: Task,
    device: Device,
    *,
    capability_code: str | None = None,
) -> bool:
    """Apply task-level constraints and the relevant work capability to a device.

    A business task can contain several resource requirements.  Automatic
    capacity planning must therefore test a transport allocation against its
    own capability, rather than incorrectly requiring the transport device to
    also implement the task's primary process.
    """

    # A task may explicitly limit equipment type, but the scheduler does not
    # infer one from a process name. The actual fleet's declared capabilities
    # and audited output rates decide which types can form the resource plan.
    required_type = str((task.params or {}).get("required_device_type") or "")
    if required_type and not _device_type_is_allowed(device.type, [required_type]):
        return False
    required_capability = capability_code or task.process_id
    processes = (device.capabilities or {}).get("processes")
    if not isinstance(processes, list) or not any(
        isinstance(process, str) and capability_codes_match(required_capability, process)
        for process in processes
    ):
        return False
    target_types = getattr(task.map_point, "device_types", []) or []
    if target_types and not _device_type_is_allowed(device.type, target_types):
        return False
    return_types = getattr(getattr(task, "return_point", None), "device_types", []) or []
    if return_types and not _device_type_is_allowed(device.type, return_types):
        return False
    requires_v2 = (
        getattr(task, "return_policy", "stay") == "return_to_point"
        or bool(getattr(task, "work_parameters", {}) or {})
    )
    return not requires_v2 or getattr(device, "protocol_version", "v1") == "v2"
