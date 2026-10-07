<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# validation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Frozen evidence records: what was run, on which commit and artifact, and what was observed (simulation, artifact comparison, UI surface, device commissioning). A passing record here is evidence for its stated scope only; it is not device, ARM64 image, or field acceptance unless it says so.

## Key Files

No index file. Entries follow a dated naming convention:

| Pattern | Description |
|---------|-------------|
| `<topic>-YYYY-MM-DD/` | Evidence folder (usually `result.md` plus raw `evidence/` such as logs and run output). Letter suffixes (`-2026-09-22b`) mark a second run the same day |
| `YYYY-MM-DD-<topic>.md` or `<topic>-YYYY-MM-DD.md` | Single-file record |
| `<topic>/` with date subfolders | Ongoing topic (`lane-junction-spike/2026-09-23`, `perception-real-video`) |

## Subdirectories

Current entries by theme (dated folders carry no AGENTS.md of their own):

| Theme | Entries |
|-------|---------|
| Core and ROS simulation | `ros-sim-core-2026-09-21`, `-2026-09-22`, `-2026-09-22b`; `core-sigterm-2026-09-22`; `core-shutdown-2026-09-23` |
| Pinky device and image | `pinky-vendor-boot-2026-09-24`, `pinky-image-sd-2026-09-27`, `pinky-native-commissioning-2026-09-27`, `pinky-camera-capture-2026-09-26`, `pinky-pro-evaluation-2026-09-24.md`, `d310-*-2026-09-27.md` (artifact comparisons), `real-drive-2026-09-30` |
| Gazebo, maps, lanes | `pinky-integrated-gazebo-2026-09-22`, `map-v2-fleet-*`, `map-260905-update-v2-*`, `scene-context-*`, `semantic-road-*`, `line-follow-modes-2026-09-21`, `lane-junction-spike`, `follow-preview-gazebo-2026-10-02.md`, `camera-ground-homography-review-2026-09-20.md`, `control-*-ros-sim-2026-09-30` |
| Perception and model tooling | `perception-real-video`, `model-tool-artifact-2026-10-01`, `model-tool-ros-sim-2026-10-01` |
| Fleet and site | `fleet-*-2026-09-29`, `site-fleet-local-smoke-2026-09-26`, `2026-09-26-site-*.md`, `web-surface-role-boundaries-2026-09-26` |
| UI/UX surfaces | `uiux-surfaces-2026-09-21` through `-2026-09-29`, `d280-product-design-baseline-2026-09-26` |
| OMX and platform | `omx-two-instance-ros-sim-2026-09-26`, `omx-demonstration-lerobot-2026-10-01`, `er2-omx-action-baseline-2026-09-29`, `pilot-omx-gazebo-2026-10-01`, `2026-09-27-platform-*.md` |

## For AI Agents

### Working In This Directory

- Records are frozen. Do not rewrite results; add a new dated entry for a re-run and link back.
- New entries use the date of the run in the name. Dated evidence must not live inside module folders under `src/`; it moves here (D-226).
- Shell scripts belong only under an `evidence/` path inside an entry.
- Raw captures, bags, and videos are gitignored (large, may be private). Record their location and hash in `result.md` instead of committing them.
- No IPs, credentials, or private network details in a record (public repo).

### Testing Requirements

```bash
python3 -m pytest test/architecture/test_document_placement.py test/architecture/test_folder_layout.py -q
```

`test_document_placement.py` fails if a dated validation path sits under `src/`; `test_folder_layout.py::test_validation_shells_stay_inside_evidence` fails on any `.sh` here outside an `evidence` directory. Harness lint also indexes these records.

### Common Patterns

- `result.md` states commit or artifact, command, observed values, and the explicit limit of the claim.

## Dependencies

### Internal

- `docs/adr/` (decisions the evidence supports), `docs/plans/`, `tools/` replay and probe scripts

### External

None.
