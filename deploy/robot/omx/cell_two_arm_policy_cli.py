#!/usr/bin/env python3
"""Supervised CLI entrypoint for D-1073 concurrent two-arm remote GPU ACT pipeline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import cell_auto_setup
import cell_bundle_emit
import cell_coordinate
import cell_job_api
import cell_params
import cell_pipeline_io
import cell_pivot
from cell_policy_entry import dry_no_runner_fallback
from cell_policy_start_gate import build_gate
import cell_policy_handoff
import cell_policy_shape
import cell_remote_policy
import cell_robot_profile
import cell_two_arm
from cell_two_arm_guard import ARMS, TwoArmChunkGuard, config_site_key
from cell_two_arm_policy import run_two_arm_policy
from cell_two_arm_verification import transfer_refusal


def parse_task_arg(raw: str) -> dict[str, Any]:
    """Accept JSON object or `src->dst` task spec strings."""
    text = raw.strip()
    if text.startswith("{"):
        doc = json.loads(text)
        if not isinstance(doc, Mapping) or "src" not in doc or "dst" not in doc:
            raise ValueError(f"JSON task spec must contain 'src' and 'dst', got {raw!r}")
        return dict(doc)
    if "->" not in text:
        raise ValueError(f"task spec must be JSON or 'src->dst', got {raw!r}")
    src, dst = (part.strip() for part in text.split("->", 1))
    return {"src": src, "dst": dst}


def parse_goal_arg(raw: str | None) -> int | list[float] | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    val = json.loads(text)
    if not isinstance(val, list):
        raise ValueError(f"goal must be integer slot or JSON float array, got {raw!r}")
    return [float(x) for x in val]


def _load_calibration(cfg: Mapping[str, Any]) -> dict[str, Any]:
    cal_path = cfg.get("calibration_path")
    if cal_path and Path(str(cal_path)).expanduser().is_file():
        raw_cal = json.loads(Path(str(cal_path)).expanduser().read_text(encoding="utf-8"))
        return cell_pivot.with_site_maps({**cfg, "sites": cfg.get("sites") or {}}, raw_cal)
    return {}


def _resolve_joint_offset(
    arm: str,
    shadow: Any,
    mcal_path: Path | None,
    ccal_path: Path | None,
    cfg: Mapping[str, Any],
    *,
    dry_run: bool,
) -> list[float]:
    jcal_path = ccal_path or (Path(str(cfg["joint_calibration_path"])).expanduser() if cfg.get("joint_calibration_path") else None)
    jcal = json.loads(jcal_path.read_text(encoding="utf-8")) if (jcal_path and jcal_path.is_file()) else None
    if getattr(shadow, "sim_rule", None) is None:
        if mcal_path is None or jcal is None:
            if not dry_run:
                raise SystemExit(f"arm {arm}: normalized checkpoint requires --model-cal-{arm} and --cell-cal-{arm}")
            return [0.0] * 6
        mcal = json.loads(mcal_path.read_text(encoding="utf-8"))
        return cell_policy_shape.calibration_offset(mcal, jcal)

    if jcal is None:
        if not dry_run:
            raise SystemExit(f"arm {arm}: sim checkpoint requires --cell-cal-{arm} or config joint_calibration_path")
        return [0.0] * 6
    for name in cell_remote_policy.JOINT_NAMES[:-1]:
        if (jcal[name]["range_min"], jcal[name]["range_max"]) != (0, 4095):
            raise SystemExit(f"arm {arm} {name}: sim checkpoint requires trained 0..4095 body tick range")
    return [0.0] * 6


def _build_jaw_spec(
    arm: str,
    cfg: Mapping[str, Any],
    lib: Mapping[str, Any],
    kin: Any,
    task: Mapping[str, Any],
) -> dict[str, Any] | None:
    if "grasp_pick" not in (lib.get("chunks") or {}):
        return None
    params = cell_params.load(cfg.get("params_path"))["values"] if cfg.get("params_path") else None
    site_key = config_site_key(cfg, task.get("src"), task.get("tier"))
    rim_z_m = cell_policy_shape.source_rim_z(dict(cfg), site_key, dict(lib)) if site_key else None
    spec = cell_policy_shape.jaw_gate_spec(dict(lib), kin, params, rim_z_m=rim_z_m)
    tcp_x_m = cell_two_arm.tcp_x_of(dict(cfg)) or lib.get("tcp_x_m")
    if spec is not None and tcp_x_m is not None:
        spec = {**spec, "tcp_x_m": float(tcp_x_m)}
    return spec


def _arm_state_gate(arm: str, root: Path | None, dry_run: bool, lib: Mapping[str, Any], shadow: Any, offset: Sequence[float], cfg: Mapping[str, Any]) -> Any:
    """The arm's start gate from its checkpoint folder. Live without the folder cannot judge a state, so it refuses; a dry run skips."""
    if root is None:
        if dry_run:
            return None
        raise ValueError(f"arm {arm}: --policy-root-{arm} is required to read the checkpoint state range (POLICY_STATE_STATS_MISSING)")
    return build_gate(root, dict(lib), shadow, offset, (cfg.get("params") or {}).get("policy.state_margin_frac"))


class _PassiveDryRunCell:
    """Read-only `--dry-run` wrapper supplying library home pose for `state` when `no runner`."""

    def __init__(self, inner: Any, pose: Sequence[float]):
        self._inner = inner
        self._pose = [float(x) for x in pose]

    def act(self, command: str, timeout: float | None = None) -> dict[str, Any]:
        if command == "state":
            return {"ok": True, "state": list(self._pose), "holding": False, "t": time.time(), "passive_source": "library_home"}
        return {"ok": False, "fault": "dry_run_passive_cell", "error": f"passive dry-run cell refuses {command!r}"}

    def checked(self, command: str, assessment: Mapping[str, Any], timeout: float | None = None) -> dict[str, Any]:
        return {"ok": False, "fault": "dry_run_passive_cell", "error": f"passive dry-run cell refuses checked {command!r}"}

    def __getattr__(self, name: str) -> Any:
        if name in ("frame", "frame_receipt"):
            return getattr(self._inner, name)
        raise AttributeError(name)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-a", type=Path, required=True)
    parser.add_argument("--config-b", type=Path, required=True)
    parser.add_argument("--endpoint-url", required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--policy-root-a", type=Path)
    parser.add_argument("--policy-root-b", type=Path)
    parser.add_argument("--revision-a", required=True)
    parser.add_argument("--revision-b", required=True)
    parser.add_argument("--library-a", type=Path, required=True)
    parser.add_argument("--library-b", type=Path, required=True)
    parser.add_argument("--task-a", required=True, help="src->dst or JSON spec")
    parser.add_argument("--task-b", required=True, help="src->dst or JSON spec")
    parser.add_argument("--goal-a", help="Optional integer slot or JSON float vector for arm_a")
    parser.add_argument("--goal-b", help="Optional integer slot or JSON float vector for arm_b")
    parser.add_argument("--model-cal-a", type=Path)
    parser.add_argument("--model-cal-b", type=Path)
    parser.add_argument("--cell-cal-a", type=Path)
    parser.add_argument("--cell-cal-b", type=Path)
    parser.add_argument("--model-site-a", default="belt")
    parser.add_argument("--model-site-b", default="belt")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument("--timeout-s", type=float, default=0.8)
    parser.add_argument("--jpeg-quality", type=int, default=cell_remote_policy.DEFAULT_JPEG_QUALITY)
    parser.add_argument("--margin-m", type=float, default=0.02)
    parser.add_argument("--min-z-m", type=float, default=-0.02)
    parser.add_argument("--proposer", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commissioning", action="store_true")
    parser.add_argument("--person-at-switch", action="store_true")
    args = parser.parse_args(argv)

    if not args.proposer.strip() or not args.operator.strip() or args.proposer.strip() == args.operator.strip():
        raise SystemExit("--proposer and --operator must be distinct non-empty identities (D-1024)")
    if not (50 <= args.jpeg_quality <= 100):
        raise SystemExit(f"--jpeg-quality must be in 50..100, got {args.jpeg_quality}")
    if not args.dry_run and not (args.commissioning and args.person_at_switch):
        raise SystemExit("live two-arm policy execution requires --commissioning --person-at-switch (D-911)")

    tasks = {"a": parse_task_arg(args.task_a), "b": parse_task_arg(args.task_b)}
    if refusal := transfer_refusal(tasks, dry_run=args.dry_run):
        print(json.dumps(refusal))
        return 1
    supervised = bool(args.commissioning and args.person_at_switch)
    configs: dict[str, dict[str, Any]] = {}
    for arm_lbl, cfg_path in (("a", args.config_a), ("b", args.config_b)):
        cfg = cell_auto_setup.load_config(cfg_path)
        cfg.pop("_commissioning", None)
        if not cfg.get("operating_profile_path"):
            raise SystemExit(f"arm {arm_lbl} config missing operating_profile_path (D-911)")
        cfg = cell_robot_profile.bind_pipeline(cfg)
        configs[arm_lbl] = cell_two_arm.attest(cfg, supervised=supervised)

    token = cell_job_api.read_token(args.token_file) if args.token_file is not None else None
    goals = {"a": parse_goal_arg(args.goal_a), "b": parse_goal_arg(args.goal_b)}
    libs = {
        "a": json.loads(args.library_a.read_text(encoding="utf-8")),
        "b": json.loads(args.library_b.read_text(encoding="utf-8")),
    }

    default_scratch = Path(os.environ.get("ROSY_SCRATCH", "D:/DevTemp")) / "two-arm-policy"
    work_dir = Path(args.work_dir) if args.work_dir is not None else default_scratch
    work_dir.mkdir(parents=True, exist_ok=True)

    cells = cell_two_arm.open_cells(configs, cell_pipeline_io.FifoCell)
    passive_arms: list[str] = []
    try:
        if args.dry_run:
            for arm in ARMS:
                if callable(act_fn := getattr(cells[arm], "act", None)):
                    st = act_fn("state")
                    if (fallback := dry_no_runner_fallback(st, True, None, libs[arm])) is not None:
                        cells[arm] = _PassiveDryRunCell(cells[arm], fallback)
                        passive_arms.append(arm)
        elif cell_two_arm.away_from_home(cells, libs):
            raise SystemExit("one or both arms are away from home before live start; return home first")

        kins = cell_two_arm.kinematics_for(
            configs,
            {"a": [(args.library_a, libs["a"])], "b": [(args.library_b, libs["b"])]},
        )
        tips = {arm: float(configs[arm].get("fingertip_m", 0.0)) for arm in ARMS}
        cal_a, cal_b = _load_calibration(configs["a"]), _load_calibration(configs["b"])
        has_sites = (
            args.model_site_a in cal_a.get("sites", {})
            and args.model_site_b in cal_b.get("sites", {})
        )
        if not args.dry_run and not has_sites:
            raise SystemExit("calibration site maps required for live rigid_of registration (D-911)")
        top_camera = cell_coordinate.shared_top_camera(configs["a"], configs["b"])
        if has_sites and not args.dry_run and top_camera is None:
            z_a = cal_a["sites"][args.model_site_a].get("z_view")
            z_b = cal_b["sites"][args.model_site_b].get("z_view")
            if (z_a is None) != (z_b is None) or (z_a is not None and abs(float(z_a) - float(z_b)) > 1e-6):
                raise SystemExit(
                    "differing or asymmetric z_view site maps require shared top camera height_m and center_px (D-911)"
                )
        rigid_ab = (
            cell_coordinate.rigid_of(cal_a, cal_b, args.model_site_a, args.model_site_b, camera=top_camera)
            if has_sites
            else (0.0, 0.0, -0.34)
        )
        rigid_map = {"a": rigid_ab, "b": (0.0, 0.0, 0.0)}

        shadows = {
            "a": cell_remote_policy.RemotePolicyShadow(
                args.endpoint_url, "arm_a", args.revision_a,
                token=token, timeout_s=args.timeout_s, jpeg_quality=args.jpeg_quality,
                policy_root=args.policy_root_a, config=configs["a"],
            ),
            "b": cell_remote_policy.RemotePolicyShadow(
                args.endpoint_url, "arm_b", args.revision_b,
                token=token, timeout_s=args.timeout_s, jpeg_quality=args.jpeg_quality,
                policy_root=args.policy_root_b, config=configs["b"],
            ),
        }
        offsets: dict[str, list[float]] = {}
        demo_ranges: dict[str, tuple[list[float], list[float]] | None] = {}
        jaw_specs: dict[str, dict[str, Any] | None] = {}
        for arm, mcal_p, ccal_p, proot in (
            ("a", args.model_cal_a, args.cell_cal_a, args.policy_root_a),
            ("b", args.model_cal_b, args.cell_cal_b, args.policy_root_b),
        ):
            sh = shadows[arm]
            if sh.goal_size is not None and goals[arm] is None:
                raise SystemExit(f"arm {arm}: checkpoint requires --goal-{arm}")
            if sh.goal_size is None and goals[arm] is not None:
                raise SystemExit(f"arm {arm}: checkpoint takes no goal")
            offsets[arm] = _resolve_joint_offset(arm, sh, mcal_p, ccal_p, configs[arm], dry_run=args.dry_run)
            demo_ranges[arm] = (
                cell_policy_shape.demonstrated_range(proot, offsets[arm])
                if (proot is not None and sh.sim_rule is None)
                else None
            )
            jaw_specs[arm] = _build_jaw_spec(arm, configs[arm], libs[arm], kins[arm], tasks[arm])

        state_gates: dict[str, Any] = {}
        for arm, root in (("a", args.policy_root_a), ("b", args.policy_root_b)):  # each arm against its own checkpoint's trained state range
            try:
                if gate := _arm_state_gate(arm, root, args.dry_run, libs[arm], shadows[arm], offsets[arm], configs[arm]):
                    state_gates[arm] = gate
            except ValueError as error:  # the usual refusal output: nothing moved
                print(json.dumps({"result": "refused", "reason": str(error)}))
                return 1

        guard = TwoArmChunkGuard(kins, rigid_map, tips, margin_m=args.margin_m, min_z_m=args.min_z_m)
        authorizers = (
            {arm: cell_policy_handoff.Authorization(cfg) for arm, cfg in configs.items()}
            if not args.dry_run
            else None
        )
        receipt = run_two_arm_policy(
            cells, shadows, libs, guard, tasks["a"], tasks["b"], work_dir,
            offsets=offsets, demo_ranges=demo_ranges, goals=goals, jaw_specs=jaw_specs, kins=kins,
            max_chunks=args.max_chunks, dry_run=args.dry_run, authorizers=authorizers,
            state_gates=state_gates,
            fold_context={"kin": kins, "rigids": rigid_map, "tips": tips, "margin_m": args.margin_m},
        )
        receipt["proposer"] = args.proposer.strip()
        receipt["operator"] = args.operator.strip()
        if passive_arms:
            receipt["passive_dry_run_arms"] = passive_arms
        if not args.dry_run and receipt.get("result") not in ("dry_run", "chunks_done", "released"):
            if bid := cell_bundle_emit.emit_two_arm_policy_failure(
                cells, configs, work_dir, receipt, tasks, {"a": args.revision_a, "b": args.revision_b},
            ):
                receipt["failure_bundle_id"] = bid
        receipt_path = work_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        summary: dict[str, Any] = {"result": receipt["result"], "task_id": receipt["task_id"], "receipt": str(receipt_path)}
        if receipt.get("failure_bundle_id"):
            summary["failure_bundle_id"] = receipt["failure_bundle_id"]
        if passive_arms:
            summary["passive_dry_run_arms"] = passive_arms
        print(json.dumps(summary))
        return 0 if receipt["result"] in ("dry_run", "chunks_done", "released") else 1
    finally:
        for cell in cells.values():
            close = getattr(cell, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    raise SystemExit(main())
