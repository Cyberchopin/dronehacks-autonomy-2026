# Team drop-in: forward depth sectors

Files here mirror the team companion workspace layout (ConnorG173/Dronehacks) so they can be copied
into it as-is: `vision/` goes at the workspace root, `tests/test_vision_forward_sectors.py` into its `tests/`.

- `vision/depth_sectors.py` is identical to `src/aegisland/depth_sectors.py` in this repository.
- Observer only: no PX4 publisher, no command. See `vision/README.md`.
- Built and unit-tested on 2026-11-06 at Stanford DroneHacks; not yet run against the simulator.

Run the offline tests from this folder:

    python3 -m pytest -q -p no:cacheprovider tests/test_vision_forward_sectors.py
