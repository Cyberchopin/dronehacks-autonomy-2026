import numpy as np

from aegisland.gps_denied import VisualDeadReckoner


def test_visual_dead_reckoning_tracks_relative_camera_translation() -> None:
    reckoner = VisualDeadReckoner()

    homography = np.array(
        [
            [1.0, 0.0, 12.0],
            [0.0, 1.0, 8.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )

    pose = reckoner.update(
        homography=homography,
        image_shape=(360, 480),
        inlier_ratio=0.8,
    )

    assert pose.valid
    assert pose.confidence == 0.8

    # Image shifts right/down, so estimated camera motion
    # is left/up in the local visual frame.
    assert pose.x < 0.0
    assert pose.y < 0.0
    assert pose.vx < 0.0
    assert pose.vy < 0.0


def test_visual_dead_reckoning_accumulates_motion() -> None:
    reckoner = VisualDeadReckoner()

    homography = np.array(
        [
            [1.0, 0.0, 10.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )

    first = reckoner.update(
        homography=homography,
        image_shape=(360, 480),
        inlier_ratio=0.9,
    )

    second = reckoner.update(
        homography=homography,
        image_shape=(360, 480),
        inlier_ratio=0.9,
    )

    assert abs(second.x) > abs(first.x)


def test_visual_dead_reckoning_degrades_when_visual_pose_is_unreliable() -> None:
    reckoner = VisualDeadReckoner()

    good_homography = np.eye(3)

    good = reckoner.update(
        homography=good_homography,
        image_shape=(360, 480),
        inlier_ratio=0.8,
    )

    degraded = reckoner.update(
        homography=None,
        image_shape=(360, 480),
        inlier_ratio=0.0,
    )

    assert good.valid
    assert degraded.confidence < good.confidence


def test_active_perception_does_not_advance_visual_dead_reckoning_twice() -> None:
    from types import SimpleNamespace

    import numpy as np

    from aegisland.gps_denied import RelativePose2D
    from aegisland.perception import OpenCVLandingPerception

    class CountingDeadReckoner:
        def __init__(self) -> None:
            self.update_count = 0
            self.current_count = 0

        def update(
            self,
            *,
            homography,
            image_shape,
            inlier_ratio,
        ):
            self.update_count += 1

            return RelativePose2D(
                x=0.0,
                y=0.0,
                vx=0.0,
                vy=0.0,
                confidence=0.85,
                valid=True,
            )

        def current(self):
            self.current_count += 1

            return RelativePose2D(
                x=0.0,
                y=0.0,
                vx=0.0,
                vy=0.0,
                confidence=0.85,
                valid=True,
            )

    class FailedCompensator:
        def compensate(
            self,
            previous_gray,
            current_gray,
        ):
            return SimpleNamespace(
                success=False,
                homography=None,
                aligned_previous=previous_gray,
                match_count=0,
                inlier_count=0,
                inlier_ratio=0.0,
            )

    perception = OpenCVLandingPerception()

    tracker = CountingDeadReckoner()

    perception.visual_dead_reckoner = tracker
    perception.motion_compensator = FailedCompensator()

    gray = np.zeros(
        (64, 64),
        dtype=np.uint8,
    )

    # Base interpretation of the physical frame.
    perception._motion(
        gray,
        gray,
        update_visual_state=True,
    )

    # Active-perception retry of that SAME physical frame.
    perception._motion(
        gray,
        gray,
        update_visual_state=False,
    )

    assert tracker.update_count == 1
    assert tracker.current_count == 1
