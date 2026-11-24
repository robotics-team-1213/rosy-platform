"""Close the 7-stage factory flow receipt bundle from an isolated prefix + downstream evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_flow_receipts import SCHEMA, STAGES, verify  # noqa: E402
from factory_isaac_handoff import prepare as prepare_isaac_handoff  # noqa: E402


def close_factory_flow(
    prefix_dir: Path,
    arm_s_evidence: Path,
    belt_evidence: Path,
    ab_evidence: Path,
    out_dir: Path,
) -> dict:
    prefix_path = prefix_dir / "prefix_receipts.json"
    site_map_path = prefix_dir / "site-map.json"
    intake_path = prefix_dir / "isaac-intake.json"
    if not intake_path.is_file():
        raise ValueError(f"missing isaac-intake.json in {prefix_dir}")

    expected_intake = json.loads(json.dumps(prepare_isaac_handoff(prefix_path, site_map_path)))
    recorded_intake = json.loads(intake_path.read_text(encoding="utf-8"))
    if recorded_intake != expected_intake:
        raise ValueError("recorded isaac-intake.json does not match verified prefix receipts")

    prefix_rows = json.loads(prefix_path.read_text(encoding="utf-8"))
    bindings = expected_intake["bindings"]
    ev_out = out_dir / "ev"
    ev_out.mkdir(parents=True, exist_ok=False)

    receipts: list[dict] = []
    for row in prefix_rows:
        copied = []
        for idx, item in enumerate(row["evidence"]):
            src = (prefix_dir / item["path"]).resolve(strict=True)
            rel = f"ev/{row['stage']}-{idx}{src.suffix or '.json'}"
            dst = out_dir / rel
            shutil.copyfile(src, dst)
            copied.append({"path": rel, "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()})
        receipts.append({**row, "evidence": copied})

    downstream = (
        (STAGES[4], arm_s_evidence),
        (STAGES[5], belt_evidence),
        (STAGES[6], ab_evidence),
    )
    for stage, src_path in downstream:
        src = src_path.resolve(strict=True)
        if not src.is_file() or src.stat().st_size == 0:
            raise ValueError(f"{stage} evidence missing or empty: {src_path}")
        json.loads(src.read_text(encoding="utf-8"))
        rel = f"ev/{stage}-0.json"
        dst = out_dir / rel
        shutil.copyfile(src, dst)
        receipts.append({
            "schema": SCHEMA, **bindings, "stage": stage, "status": "pass",
            "evidence": [{"path": rel, "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}],
        })

    (out_dir / "site-map.json").write_bytes(site_map_path.read_bytes())
    (out_dir / "isaac-intake.json").write_bytes(intake_path.read_bytes())
    receipts_file = out_dir / "receipts.json"
    receipts_file.write_text(json.dumps(receipts, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

    errors, summary = verify(receipts_file)
    if errors:
        raise ValueError("receipt verification failed: " + "; ".join(errors))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix-dir", type=Path, required=True)
    parser.add_argument("--arm-s-evidence", type=Path, required=True)
    parser.add_argument("--belt-evidence", type=Path, required=True)
    parser.add_argument("--ab-evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = close_factory_flow(
            args.prefix_dir, args.arm_s_evidence, args.belt_evidence, args.ab_evidence, args.out,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"world_factory_close: {exc}\n")
    print(json.dumps({
        "pass": True,
        "stages": summary["stages"],
        "evidence_files": summary["evidence_files"],
        "bindings": summary["bindings"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
