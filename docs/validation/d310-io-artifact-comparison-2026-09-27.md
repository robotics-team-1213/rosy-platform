# D-310 IO ARM64 image comparison — 2026-09-27

## Fixed inputs

| Image | Clean source revision | OCI manifest |
|---|---|---|
| Pre-move IO closure fix | `d6b9c24194c04c8245366fbd5ccf630d0b848419` | `sha256:de78854df19622d4075a43d3a59433c4b7fe94adb9579fdde733096b3bcc349d` |
| D-310 combined source candidate | `f7dae4d26438a92cdcabe1e502cb5bcb420f76e8` | `sha256:6b9b7404bd30889fe2e0e4318bd444832cc9012dbc0d26d627ada5e53b58144e` |

Both builds used the same pinned ARM64 ROS Jazzy base, build arguments, and external dependencies. The source revision and the planned Docker `COPY` paths changed with the package move. The pre-move baseline includes the independently verified `web_common` IO closure fix. The original pre-move IO image at `b0609dc6` installed only eight overlay packages and omitted `web_common`, so comparing that defective closure to the moved candidate would misattribute an intentional dependency fix to the folder move. These are local OCI images, not signed or deployed releases.

## Installed image readback

The same temporary readback stage ran against each completed image. Each row below compares the **entire output file byte for byte**; the SHA-256 values are hashes of the sorted readback manifests, not of the OCI image. Both images passed the final installed web asset and `control.web_http.web_common_dir` resolver probe.

| Readback | Both images | Manifest SHA-256 |
|---|---:|---|
| `dpkg-query` name and version inventory | 1,538 entries, exact match | `sha256:4477CD8F4EF0C186DBAAEC840AB6A5CA15C2862B13D361EF0EF2848AC45C43D4` |
| Installed overlay ament package inventory | 9 packages, exact match | `sha256:A3B679550CC7A669EBDCEF3BA33D23F36B881627CD782C016508C23AFB32171B` |
| `ros2 pkg prefix` for `bringup`, `omx`, `omx_adapter`, `web_common` | all `/opt/rosy_ws/install`, exact match | `sha256:79C82C3654ADD88062758BB9D7B2FB7FB877735E35A5BF0FC1817CE272A458E5` |
| Installed package share/config/launch file paths and content hashes | 395 files, exact match | `sha256:7E77D2D9CB5CC212C34FF4D66EA7DCBEBD6841BE313B32BA0471A1BECD2FCB9F` |
| Installed package entrypoint paths and modes | 19 executables, all `755`, exact match | `sha256:8C1F1E20565B9B7F8182343EBA7A37082B6B7955C89A72A5C03F8A8F2F8DABDF` |
| Installed entrypoint wrapper content hashes | 19 files, exact match | `sha256:0B60C225B2351C54377E7A8F6CA0FC311483042F1B64C22D6E07E426FD426B27` |

The nine overlay packages are `bringup`, `control`, `description`, `interfaces`, `navigation`, `omx`, `omx_adapter`, `sllidar_ros2`, and `web_common`. Both final images imported `control_msgs.action`, `visualization_msgs.msg`, `omx_adapter.ros_runtime`, and `control.web_node`. Both IO builds and their final probes exited successfully.

Raw evidence: `X:\DevTemp\rosy-d310-io-baseline-fixed-d6.log`, `X:\DevTemp\rosy-d310-io-combined-f7.log`, `X:\DevTemp\rosy-d310-io-full-evidence-d6.log`, `X:\DevTemp\rosy-d310-io-full-evidence-f7.log`, and their six readback files in `X:\DevTemp\rosy-d310-io-full-evidence-{d6,f7}\`. The f7 local OCI tar is `X:\DevTemp\rosy-d310-io-combined-f7.oci.tar` (1,003,081,216 bytes). The source revisions and OCI manifests above identify the actual builds; image digest equality is not the equivalence criterion.

## Gate decision

This establishes **IO image installed-closure equivalence for the recorded pre-move and moved source revisions**. It does not prove a physical OMX owner, single operational command path, stop behavior, Pi installation, or field operation. [CORE image comparison](d310-core-artifact-comparison-2026-09-27.md) is a separate result. The native Pinky payload still requires a clean candidate checkout on a real aarch64/Jazzy builder, full installed inventory and executable/share readback against its pre-move baseline. At the time of this comparison D-310 was Proposed and `main` folder integration was HOLD. The later source-only acceptance and requested local merge are recorded in D-310; whole-change `ARTIFACT_EQUIVALENT`, DEVICE, and FIELD remain HOLD.
