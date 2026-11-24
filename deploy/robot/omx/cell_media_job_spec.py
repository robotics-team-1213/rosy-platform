"""Non-motion media, dataset, and policy-bundle staging job specs for `cell_job_spec` (D-1072 PR-3)."""
from __future__ import annotations

import re

from cell_job_validators import (
    IMAGES_SPEC,
    MANIFEST_FILE,
    NAME,
    SHA256,
    VIEW,
    _int_range,
    _match,
    _repo_id,
    _workdir_rel_path,
)

MEDIA_JOBS = {
    "upkeep_check": {
        "script": "cell_upkeep.py",
        "argv": ["{manifest}", "--mode", "autonomous"],
        "params": {"manifest": _match(MANIFEST_FILE)},
        "optional": {"out": _workdir_rel_path},
    },
    "capture_clip": {
        "script": "cell_media_jobs.py",
        "argv": ["capture-clip", "--view", "{view}", "--duration-s", "{duration_s}"],
        "params": {"view": _match(VIEW), "duration_s": _int_range(1, 15)},
        "optional": {"out_dir": _workdir_rel_path, "fps": _int_range(1, 30)},
    },
    "convert_episodes": {
        "script": "cell_media_jobs.py",
        "argv": ["convert-episodes", "--episodes", "{episodes}", "--out", "{out}", "--repo-id", "{repo_id}"],
        "params": {"episodes": _workdir_rel_path, "out": _workdir_rel_path, "repo_id": _repo_id},
        "optional": {
            "fps": _int_range(1, 60),
            "images": _match(IMAGES_SPEC),
            "outcome": _match(re.compile(r"success|failed|failure")),
        },
    },
    "transfer_dataset": {
        "script": "cell_media_jobs.py",
        "argv": ["transfer-dataset", "--collection", "{collection}"],
        "params": {"collection": _match(NAME)},
        "optional": {},
    },
    "stage_policy_bundle": {
        "script": "cell_media_jobs.py",
        "argv": ["stage-policy-bundle", "--run-id", "{run_id}", "--target-dir", "{target_dir}"],
        "params": {"run_id": _match(NAME), "target_dir": _workdir_rel_path},
        "optional": {"expected_manifest_sha256": _match(SHA256)},
    },
}
