"""Per-step item_at_pose predicates fixed at resolution (D-403 §5, C4b 1b C1).

Judging and the public ingress live in cell_goal_evidence_service (ported from main); this module
only stores each step's predicate, so a later config change cannot move it.

A multi-arm step (recipe/3, D-781 §5) stores ``goal_predicates``: one predicate per primary and
alternate arm, each compiled from that arm's own inputs, so each is in that arm's ``robot_base``
frame. The step run by an alternate arm is judged against the alternate's predicate (D-779 §4).
"""

from __future__ import annotations

from typing import Mapping

from rosy.execution.site.item_pose import ItemPoseTolerance, centre_above_tcp_m, step_goal_predicate


def _offsets(item_geometry: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    return {item: centre_above_tcp_m(grasp_depth_m=values["grasp_depth_m"], height_m=values["height_m"])
            for item, values in item_geometry.items()}


def attach_goal_predicates(document: dict, item_geometry: Mapping[str, Mapping[str, float]],
                           tolerance: ItemPoseTolerance) -> None:
    """Fix each step's item_at_pose predicate at resolution. ``item_geometry`` comes from the
    validated recipe (the compiler's item_geometry); nothing is defaulted here (1c P3)."""
    offsets = _offsets(item_geometry)
    for step in document["steps"]:
        step["goal_predicate"] = step_goal_predicate(step["inputs"], tolerance, offsets[step["inputs"]["item"]])


def attach_arm_goal_predicates(submission: dict, sku_geometry: Mapping[str, Mapping[str, float]],
                               tolerance: ItemPoseTolerance) -> None:
    """Fix, per multi-arm step, one predicate for every arm that may run it, in that arm's frame.
    ``sku_geometry`` is the recipe/3 geometry keyed by sku; each arm's inputs name the sku."""
    offsets = _offsets(sku_geometry)
    for step in submission["steps"]:
        actions = step["placement"]["actions"]
        step["goal_predicates"] = {role: step_goal_predicate(inputs, tolerance, offsets[inputs["sku"]])
                                   for role, inputs in sorted(actions.items())}


__all__ = ["attach_arm_goal_predicates", "attach_goal_predicates", "make_cell_job_resolver"]


def make_cell_job_resolver(compiler, item_pose_tolerance):
    """Compose canonical Cell submission with optional independent goal predicates."""
    if compiler is None:
        return None
    if not callable(getattr(compiler, "compile_submission", None)):
        raise ValueError("cell compiler must provide compile_submission")

    from .cell_mixed_submission import compile_mixed_submission, is_mixed

    def resolve(candidate, *, workcell_id, instance_id):
        if is_mixed(candidate):  # D-781: recipe/3 -> multi-arm Job, one predicate per arm frame
            submission = compile_mixed_submission(candidate, compiler=compiler, workcell_id=workcell_id,
                                                  instance_id=instance_id)
            if item_pose_tolerance is not None:
                attach_arm_goal_predicates(submission, compiler.item_geometry(candidate["recipe"]),
                                           item_pose_tolerance)
            return submission
        document = compiler.compile_submission(
            candidate, workcell_id=workcell_id, instance_id=instance_id)
        if item_pose_tolerance is not None:
            attach_goal_predicates(document, compiler.item_geometry(candidate["recipe"]), item_pose_tolerance)
        return document

    return resolve
