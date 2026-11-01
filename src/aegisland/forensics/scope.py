"""Fixed interpretation boundary shared by every report type."""

UNASSESSED = (
    "outside_sampled_roi",
    "beyond_probe_plane",
    "occluded_volume",
    "swept_vehicle_volume",
    "dynamic_obstacles",
)


def geometry_boundary() -> dict:
    return {
        "scope": "local_sensing_plane_only",
        "knowledge": "unknown",
        "full_3d_traversability": "UNKNOWN",
        "supports_3d_traversal": False,
        "authority_change": "NONE",
        "executed": False,
        "unassessed": list(UNASSESSED),
        "detail": "Local depth/width, sensor agreement and descent geometry do not establish "
        "3D traversability, landing safety or execution permission.",
    }
