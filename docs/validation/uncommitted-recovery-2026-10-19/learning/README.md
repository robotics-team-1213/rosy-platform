# Historical learning worktree recovery — 2026-10-19

These are frozen historical documents recovered from pending work, not instructions
to execute the plans or evidence of current platform acceptance. The original
worktrees and their uncommitted files remain intact. Both distinct integrated
pipeline plan versions are preserved in full, byte for byte.

The recovery branch `docs/recover-learning-wip` started from current platform main.
It does not merge the old history. At inspection main was `bc2239c2f3`; it has no
D-771 ADR, integrated pipeline plan corpus, or `learning/registry/catalog` holder.
The unrelated `D:/Dev/Robot/rosy-docs` repository contains Confluence design
documents and is not the destination for these plans. Restoring the absent feature
requires a separate reviewed port of its contracts, implementation and evidence.

## Sources

Each filename below keeps its original bytes. Paths inside the documents and
their relative links describe the old checkout; missing historical prerequisites
are deliberately not recreated. Test counts and acceptance statements inside the
copies belong to their original revisions and have not been revalidated here.

| Archive directory | Original worktree / branch | Original HEAD | Original paths |
|---|---|---|---|
| `learning-delivery/` | `.worktrees/learning-delivery`, `feat/integrated-learning-pipeline` | `2436c0c82b2a22d4bf58294c7d06cb1f3f1a1d3d` | `docs/plans/2026-10-16-integrated-learning-pipeline.md`, `docs/plans/2026-10-17-signed-catalog-import.md`, `docs/plans/2026-10-17-video-reader-staging-and-acceptance.md` |
| `learning-plan/` | `.worktrees/learning-plan`, `docs/integrated-learning-plan` | `61ffacc0911a61c6ecc6171a4a4adb98b0200033` | `docs/plans/2026-10-16-integrated-learning-pipeline.md`, untracked `docs/plans/2026-10-17-perception-lineage.md`, untracked `docs/plans/2026-10-17-video-reader-integration.md` |

`learning-plan/logs-pending-row.md` preserves only the pending `docs/logs.md` row
and its three preceding context rows. It does not copy the unrelated historical
journal into the current journal. `sha256.json` records the six complete source
documents' SHA-256 digests and byte counts for independent recovery checks.

## Already incorporated source changes

The pending `v13-map-labels` split is already present through `8bef4859fe`
(`fix: preserve reviewed v13-map-labels pending changes`) and its merge
`b43efd0155`, both ancestors of current main. Current consumers keep detection in
the capture tool and odometry fusion in curation:

| Original path | Current path |
|---|---|
| `learning/training/perception/dataset/ceiling_pose.py` | `learning/curation/perception/ceiling_pose.py` |
| `learning/training/perception/dataset/map_projected_drivable.py` | `learning/curation/perception/map_projected_drivable.py` |
| `learning/training/perception/test/test_ceiling_pose.py` | `test/learning/perception/test_ceiling_pose.py` |
| `tools/capture/ceiling_poses.py` | same path |
| `tools/capture/test/test_ceiling_poses.py` | same path |
| `tools/capture/map_labels_run.sh` | same path |

The capture script invokes `ceiling_poses.py`; fusion imports no overhead detector.
The capture tool's curation import was subsequently repaired by `8a0ff38598` and
the overhead holder was moved to `operations/overhead`. Reapplying the old paths
would undo those repairs. The untracked original detector is byte-identical after
newline normalization to the one saved in `8bef4859fe`.

The pending `d427-bulk` test assertion is superseded by `a0eb51478f` in
`operations/fleet/test/test_cli.py`: the test accepts both installed `web_common`
and source `web`, and additionally checks `shared-assets.json`. This commit is an
ancestor of current main. No duplicate source or test edits are needed.

## Verification scope

Recovery checks compare the archived documents against the untouched worktrees.
Platform document-placement, folder-layout and governance checks run through the
remote runner and the official landing workflow. These checks establish document
preservation and repository compatibility only. They do not establish the old
D-771 test claims, GPU training, deployed services, device behavior or field acceptance.
