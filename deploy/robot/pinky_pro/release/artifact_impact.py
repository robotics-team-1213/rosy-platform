#!/usr/bin/env python3
"""Select the smallest Pinky artifact required by a source revision diff.

This is a conservative release-planning aid, not a release approval. Unknown
Pinky paths are held for review. Signature, compatibility, installation, and
device-readback gates remain owned by their existing release procedures.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def _colcon_roots() -> tuple[str, ...]:
    """D-427: the native payload builds every colcon root in the platform manifest.

    Loads tools/harness/colcon_roots.py from this file's own checkout, so the module
    is not copy-portable: run it from a repository tree.
    """
    reader = Path(__file__).resolve().parents[4] / "tools" / "harness" / "colcon_roots.py"
    spec = importlib.util.spec_from_file_location("rosy_colcon_roots", reader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.colcon_roots()


COLCON_ROOT_PREFIXES = tuple(f"{root}/" for root in _colcon_roots())
IMAGE_PREFIXES = (
    "deploy/robot/pinky_pro/image/",
    "deploy/robot/pinky_pro/native/",
    "deploy/robot/pinky_pro/config/",
    "deploy/robot/pinky_pro/udev/",
    "deploy/robot/pinky_pro/modprobe/",
)
NO_PINKY_PREFIXES = (
    "docs/",
    "test/",
    "tools/harness/",
    ".github/",
    ".claude/",
    ".impeccable/",
    "deploy/site/",
    "deploy/robot/omx/",
)
NO_PINKY_FILES = {
    "AGENTS.md",
    "README.md",
    "STATUS.md",
    "deploy/index.md",
    "deploy/logs.md",
    "deploy/progress.md",
}


@dataclass(frozen=True)
class PathImpact:
    path: str
    impact: str
    reason: str


@dataclass(frozen=True)
class ImpactReport:
    impact: str
    paths: tuple[PathImpact, ...]
    base: str | None = None
    head: str | None = None


class ImpactSelectionError(RuntimeError):
    """The requested revision diff could not be proven."""


def _ota_units() -> set[str]:
    native = Path(__file__).resolve().parent.parent / 'native'
    units = set()
    for filename, variable in (('sync-image-layer.py', 'UNITS'), ('image_layer_boot.py', 'FEATURE_UNITS')):
        tree = ast.parse((native / filename).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == variable for t in node.targets):
                units.update(item.value for item in node.value.elts if isinstance(item, ast.Constant))
    return units


def _classify_path(path: str) -> PathImpact:
    normalized = path.replace("\\", "/").removeprefix("./")
    if not normalized or normalized.startswith("/") or "../" in normalized:
        return PathImpact(path, "review", "path is not a normalized repository-relative path")

    name = normalized.rsplit("/", 1)[-1]
    if normalized in NO_PINKY_FILES or name in {"AGENTS.md", "README.md"}:
        return PathImpact(path, "none", "repository guidance or deployment harness record")
    if normalized.startswith(NO_PINKY_PREFIXES):
        return PathImpact(path, "none", "documentation, tests, CI, or a separate product/site surface")
    if normalized.startswith(COLCON_ROOT_PREFIXES):
        return PathImpact(path, "native-payload", "workspace source is built into the native payload")
    if normalized in {'deploy/robot/pinky_pro/image/first-boot/' + name
                      for name in ('rosy-first-boot.py', 'rosy-first-boot.sh')}:
        return PathImpact(path, 'native-payload', 'signed boot catalog; bridge capability and compatibility gates required')
    if normalized.startswith('deploy/robot/pinky_pro/native/'):
        if name.endswith(('.service', '.timer', '.path', '.target')) and name not in _ota_units():
            return PathImpact(path, 'review', 'unit has no installed image-layer destination')
        return PathImpact(path, 'native-payload', 'signed native runtime; installed-image compatibility gates required')
    if normalized.startswith(IMAGE_PREFIXES):
        return PathImpact(path, "flashable-image", "Pinky image, host-service, or board configuration input")
    if normalized.startswith("deploy/robot/pinky_pro/release/public-keys/"):
        return PathImpact(path, "flashable-image", "device trust-anchor change requires image-level review")
    if normalized.startswith("deploy/robot/pinky_pro/"):
        return PathImpact(path, "review", "Pinky operator or release tooling needs an explicit delivery decision")
    return PathImpact(path, "review", "path is not covered by the Pinky artifact policy")


def classify_paths(paths: list[str] | tuple[str, ...]) -> ImpactReport:
    """Classify changed repository paths with review taking precedence."""
    classified = tuple(_classify_path(path) for path in sorted(set(paths)))
    if any(item.impact == "review" for item in classified):
        impact = "review"
    elif any(item.impact == "flashable-image" for item in classified):
        impact = "flashable-image"
    elif any(item.impact == "native-payload" for item in classified):
        impact = "native-payload"
    else:
        impact = "none"
    return ImpactReport(impact=impact, paths=classified)


def delivery_policy(paths: list[str] | tuple[str, ...]) -> str:
    """Executable CD route; delta additionally needs authenticated artifact checks.

    Host release tooling does not change the robot's installed payload. Unknown
    paths retain the existing review gate. OS delivery requires its own approval.
    """
    robot_paths = [path for path in paths if not path.startswith("tools/release/")]
    impact = classify_paths(robot_paths).impact
    return {"none": "none", "native-payload": "full-payload",
            "flashable-image": "os-image", "review": "review"}[impact]


def select_impact(base: str, head: str, *, repository: Path | str = ".") -> ImpactReport:
    """Classify changes on the candidate side of the merge-base diff."""
    if not base.strip() or not head.strip():
        raise ImpactSelectionError("both --base and --head revisions are required")
    command = [
        "git",
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        f"{base}...{head}",
        "--",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=repository,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImpactSelectionError(f"unable to inspect Git diff: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ImpactSelectionError(detail or "git diff could not compare the supplied revisions")
    paths = [entry.decode("utf-8", errors="surrogateescape") for entry in result.stdout.split(b"\0") if entry]
    classified = classify_paths(paths)
    return ImpactReport(
        impact=classified.impact,
        paths=classified.paths,
        base=base,
        head=head,
    )


def _summary(report: ImpactReport) -> str:
    details = {
        "none": "No Pinky device artifact is indicated by these changes.",
        "native-payload": (
            "Use the native-payload workflow for a compatible installed image; "
            "compare the payload ROS package inventory with the target image before signing or transfer."
        ),
        "flashable-image": (
            "Use the native ARM64 flashable-image workflow; signing, card readback, and device acceptance remain separate gates."
        ),
        "review": "HOLD: review the unclassified Pinky paths and select the delivery scope explicitly.",
    }
    lines = [
        f"PINKY_ARTIFACT={report.impact}",
        details[report.impact],
        f"Changed paths: {len(report.paths)}",
    ]
    detail_impact = "review" if report.impact == "review" else report.impact
    relevant = [item for item in report.paths if item.impact == detail_impact]
    if relevant:
        lines.append("Relevant paths:")
        lines.extend(f"  {item.path} - {item.reason}" for item in relevant[:12])
        if len(relevant) > 12:
            lines.append(f"  ... and {len(relevant) - 12} more; use --json for the full breakdown")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="confirmed source_revision from the installed image manifest")
    parser.add_argument("--head", required=True, help="candidate source revision")
    parser.add_argument("--repo-root", default=".", help="repository path (default: current directory)")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args(argv)

    try:
        report = select_impact(args.base, args.head, repository=args.repo_root)
    except ImpactSelectionError as exc:
        print(f"PINKY_ARTIFACT=HOLD: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(_summary(report))
        for item in report.paths:
            print(f"{item.impact:16} {item.path} - {item.reason}")
    return 0 if report.impact != "review" else 3


if __name__ == "__main__":
    raise SystemExit(main())
