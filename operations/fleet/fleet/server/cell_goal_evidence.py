"""Per-step item_at_pose predicates fixed at resolution (D-403 §5, C4b 1b C1).

Judging and the public ingress live in cell_goal_evidence_service (ported from main); this module
only stores each step's predicate, so a later config change cannot move it.
"""

from __future__ import annotations

from typing import Mapping

from rosy.execution.site.item_pose import ItemPoseTolerance, centre_above_tcp_m, step_goal_predicate


def attach_goal_predicates(document: dict, item_geometry: Mapping[str, Mapping[str, float]],
                           tolerance: ItemPoseTolerance) -> None:
    """Fix each step's item_at_pose predicate at resolution. ``item_geometry`` comes from the
    validated recipe (the compiler's item_geometry); nothing is defaulted here (1c P3)."""
    offsets = {item: centre_above_tcp_m(grasp_depth_m=values["grasp_depth_m"], height_m=values["height_m"])
               for item, values in item_geometry.items()}
    for step in document["steps"]:
        step["goal_predicate"] = step_goal_predicate(step["inputs"], tolerance, offsets[step["inputs"]["item"]])


__all__ = ["attach_goal_predicates", "make_cell_job_resolver"]


def make_cell_job_resolver(compiler, item_pose_tolerance):
    """Compose canonical Cell submission with optional independent goal predicates."""
    if compiler is None:
        return None
    from rosy.execution.site.cell_submission import compile_cell_submission

    def resolve(candidate, *, workcell_id, instance_id):
        submission = compile_cell_submission(
            candidate, compiler=compiler, workcell_id=workcell_id, instance_id=instance_id)
        document = submission.as_store_document()
        if item_pose_tolerance is not None:
            attach_goal_predicates(document, compiler.item_geometry(candidate["recipe"]), item_pose_tolerance)
        return document

    return resolve
