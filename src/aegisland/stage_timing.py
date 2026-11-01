"""Profiling-only statement spans compiled from production methods, never a fork of them.

Baseline methods are untouched. Instrumented methods exist only on the replay instance
inside instrument(); the original instance attributes are restored even on failure.
"""

import ast
import inspect
import textwrap
import time
from contextlib import contextmanager
from types import MethodType

SCHEMA_VERSION = 1

# Assignment names are explicit semantic boundaries, independent of source line numbers.
NAMES = {
    "observe": {
        "started": "clock",
        "frame": "preprocess.resize",
        "gray": "preprocess.bgr_to_gray",
        "blurred": "preprocess.gaussian_blur",
        "edges": "structure.canny",
        "texture": "texture.absolute_u8",
        "reference_gray": "motion.reference_select",
        "motion_mask": "motion",
        "perception_quality": "quality",
        "candidates": "grid",
        "lower": "evidence.region",
        "obstacle_risk": "evidence.obstacle_risk",
        "motion_risk": "evidence.motion_risk",
        "contrast": "evidence.contrast",
        "dynamic_range": "evidence.dynamic_range",
        "confidence": "evidence.confidence",
        "payload": "evidence.payload",
        "evidence_id": "evidence.identity",
        "elapsed_ms": "evidence.processing_clock",
        "notes": "evidence.notes",
        "motion_object_center": "evidence.motion_center",
        "evidence": "evidence.construction",
        "annotated": "output.annotation",
        "return": "output.result",
    },
    "enhance_for_active_perception": {
        "lab": "retry.bgr_to_lab",
        "light": "retry.split",
        "return": "retry.lab_to_bgr",
    },
    "_resize": {"height": "resize.shape", "ratio": "resize.ratio", "return": "resize.result"},
    "_motion": {
        "raw_flow": "motion.raw_flow",
        "raw_magnitude": "motion.raw_magnitude",
        "compensation": "motion.compensation",
        "visual_pose": "motion.localization",
        "aligned_reference": "motion.aligned_reference",
        "flow": "motion.residual_flow",
        "magnitude": "motion.residual_magnitude",
        "raw_mean": "motion.raw_mean",
        "compensated_mean": "motion.residual_mean",
        "suppression_ratio": "motion.suppression",
        "mask": "motion.threshold",
        "kernel": "motion.kernel",
        "contours": "motion.contours",
        "minimum_area": "motion.minimum_area",
        "boxes": "motion.boxes",
        "metrics": "motion.metrics",
        "return": "motion.result",
    },
    "_score_grid": {
        "height": "grid.shape",
        "cell_h": "grid.cell_height",
        "cell_w": "grid.cell_width",
        "candidates": "grid.initialize",
        "image_diag": "grid.diagonal",
        "relative_threshold": "grid.appearance_threshold",
        "appearance_mask": "grid.appearance_mask",
        "return": "grid.sort",
    },
    "compensate": {
        "prev_keypoints": "compensation.orb_previous",
        "curr_keypoints": "compensation.orb_current",
        "knn_matches": "compensation.match",
        "matches": "compensation.matches",
        "source_points": "compensation.source_points",
        "destination_points": "compensation.destination_points",
        "homography": "compensation.homography",
        "inlier_count": "compensation.inlier_count",
        "inlier_ratio": "compensation.inlier_ratio",
        "height": "compensation.shape",
        "aligned_previous": "compensation.warp",
        "return": "compensation.result",
    },
    "analyze": {
        "mean_brightness": "quality.brightness",
        "bright_ratio": "quality.bright_ratio",
        "dark_mask": "quality.dark_mask",
        "dark_ratio": "quality.dark_ratio",
        "sharpness": "quality.sharpness",
        "entropy_bits": "quality.entropy",
        "keypoints": "quality.features",
        "feature_count": "quality.feature_count",
        "largest_dark_region_ratio": "quality.dark_regions",
        "image_score": "quality.image_score",
        "geometry_score": "quality.geometry_score",
        "failure_type": "quality.classification",
        "caps": "quality.caps",
        "cap": "quality.cap",
        "return": "quality.result",
    },
}


class Collector:
    def __init__(self, clock=None):
        self.clock = clock or time.perf_counter_ns
        self.rows = []
        self.stack = []

    @contextmanager
    def span(self, name):
        parent = self.stack[-1] if self.stack else None
        entry = {
            "stage": name,
            "parent": parent["stage"] if parent else "",
            "parent_id": parent["sample_id"] if parent else -1,
            "children_ns": 0,
            "sample_id": len(self.rows),
        }
        self.rows.append(entry)
        self.stack.append(entry)
        start = self.clock()
        try:
            yield
        finally:
            elapsed = self.clock() - start
            self.stack.pop()
            entry.update(
                inclusive_ns=elapsed, exclusive_ns=elapsed - entry.pop("children_ns"), calls=1
            )
            if parent is not None:
                parent["children_ns"] += elapsed

    def call(self, name, function, *args, **kwargs):
        with self.span(name):
            return function(*args, **kwargs)


def _key(statement):
    if isinstance(statement, ast.Assign):
        target = statement.targets[0]
    elif isinstance(statement, ast.AnnAssign):
        target = statement.target
    else:
        return "return" if isinstance(statement, ast.Return) else None
    while isinstance(target, (ast.Tuple, ast.List)):
        target = target.elts[0]
    return target.id if isinstance(target, ast.Name) else None


def _compile(method, collector, schema):
    function = method.__func__
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    node = tree.body[0]
    counts = {}
    rewritten = []
    for statement in node.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            rewritten.append(statement)  # docstring
            continue
        key = _key(statement)
        name = NAMES[node.name].get(key)
        if isinstance(statement, ast.If):
            condition = ast.unparse(statement.test)
            if node.name == "observe":
                name = (
                    "preprocess.retry_clahe"
                    if "active_perception" == condition and "gray =" in ast.unparse(statement)
                    else "output.reference_update"
                    if condition == "not active_perception"
                    else "evidence.motion_center_select"
                    if condition == "motion_boxes"
                    else "evidence.retry_confidence"
                )
            elif node.name == "_motion":
                name = (
                    "motion.reference_check"
                    if "reference_gray is None" in condition
                    else "motion.localization"
                )
            elif node.name == "compensate":
                name = "compensation.validation"
            elif node.name == "_resize":
                name = "resize.noop_check"
            else:
                name = "quality.validation" if "gray" in condition else "quality.score_adjustment"
        elif isinstance(statement, ast.For):
            name = (
                "grid.candidate_scoring"
                if node.name == "_score_grid"
                else "compensation.ratio_filter"
            )
        if name is None:
            raise ValueError(f"Unmapped stage: {node.name}: {ast.unparse(statement)}")
        # Distinguish repeated operations explicitly; names are stable for this schema version.
        if node.name == "observe" and key == "edges" and counts.get(name):
            name = "structure.close"
        if node.name == "enhance_for_active_perception" and key == "light" and counts.get(name):
            name = "retry.clahe_lightness"
        if node.name == "_motion" and key == "mask":
            name = (
                "motion.open"
                if counts.get("motion.threshold") and not counts.get("motion.open")
                else "motion.dilate"
                if counts.get("motion.open")
                else name
            )
        if node.name == "_score_grid" and key == "appearance_mask" and counts.get(name):
            name = "grid.appearance_open"
        if node.name == "compensate" and key == "matches" and counts.get(name):
            name = "compensation.sort_matches"
        counts[name] = counts.get(name, 0) + 1
        definition = {"method": node.name, "boundary": ast.unparse(statement)}
        if definition not in schema.setdefault(name, []):
            schema[name].append(definition)
        # Split nested native calls without changing evaluation order or production code.
        inner = {
            "texture.absolute_u8": ("Laplacian", "texture.laplacian"),
            "output.annotation": ("copy", "output.frame_copy"),
            "retry.lab_to_bgr": ("merge", "retry.merge"),
        }.get(name)
        if inner:
            attribute, inner_name = inner

            class WrapCall(ast.NodeTransformer):
                def visit_Call(self, call_node, attribute=attribute, inner_name=inner_name):
                    self.generic_visit(call_node)
                    if (
                        isinstance(call_node.func, ast.Attribute)
                        and call_node.func.attr == attribute
                    ):
                        schema.setdefault(
                            inner_name, [{"method": node.name, "boundary": ast.unparse(call_node)}]
                        )
                        return ast.copy_location(
                            ast.Call(
                                ast.Attribute(
                                    ast.Name("_stage_collector", ast.Load()), "call", ast.Load()
                                ),
                                [ast.Constant(inner_name), call_node.func, *call_node.args],
                                call_node.keywords,
                            ),
                            call_node,
                        )
                    return call_node

            statement = WrapCall().visit(statement)
        call = ast.Call(
            ast.Attribute(ast.Name("_stage_collector", ast.Load()), "span", ast.Load()),
            [ast.Constant(name)],
            [],
        )
        if isinstance(statement, ast.If):
            # Only executed branches produce samples. Condition work remains in parent residual.
            statement.body = [
                ast.copy_location(ast.With([ast.withitem(call)], statement.body), statement)
            ]
            if statement.orelse:
                statement.orelse = [
                    ast.copy_location(ast.With([ast.withitem(call)], statement.orelse), statement)
                ]
            rewritten.append(statement)
        else:
            wrapped = ast.With([ast.withitem(call)], [statement])
            rewritten.append(ast.copy_location(wrapped, statement))
    node.body = rewritten
    ast.fix_missing_locations(tree)
    namespace = {**function.__globals__, "_stage_collector": collector}
    # Only trusted local production source is compiled; no external input is evaluated.
    exec(compile(tree, function.__code__.co_filename, "exec"), namespace)  # noqa: S102
    return MethodType(namespace[node.name], method.__self__)


@contextmanager
def instrument(model, collector, schema=None, *, capture_grid=False):
    """Compile only explicitly listed production methods; never compile capture overrides.

    Snapshot callers explicitly route the production grid implementation through a
    separate slot, leaving their capture callback untouched. All other overrides
    are rejected rather than silently instrumenting or replacing helper algorithms.
    """
    from .motion_compensation import CameraMotionCompensator
    from .perception import OpenCVLandingPerception
    from .perception_quality import PerceptionQualityMonitor

    schema = {} if schema is None else schema
    saved = []
    try:
        for owner, production_class, names in (
            (
                model,
                OpenCVLandingPerception,
                ("observe", "enhance_for_active_perception", "_resize", "_motion", "_score_grid"),
            ),
            (model.motion_compensator, CameraMotionCompensator, ("compensate",)),
            (model.perception_quality_monitor, PerceptionQualityMonitor, ("analyze",)),
        ):
            for name in names:
                function = production_class.__dict__[name]
                if name == "_score_grid" and capture_grid:
                    name = "_stage_score_grid"
                elif getattr(getattr(owner, name), "__func__", None) is not function:
                    raise ValueError(f"Unsupported non-production override: {name}")
                method = MethodType(function, owner)
                previous = owner.__dict__.get(name)
                present = name in owner.__dict__
                replacement = _compile(method, collector, schema)
                saved.append((owner, name, present, previous))
                setattr(owner, name, replacement)
        yield
    finally:
        for owner, name, present, previous in reversed(saved):
            if present:
                setattr(owner, name, previous)
            else:
                delattr(owner, name)
