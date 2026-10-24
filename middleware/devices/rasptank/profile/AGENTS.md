# RaspTank source profile

Parent: `../../../AGENTS.md` and the device-family guidance in `../../AGENTS.md`.

This config-only ROS package is named `rasptank_metal`. It installs `config/{profile,capabilities,core}.yaml` to `share/rasptank_metal/config` for the existing CORE model selector. It adds no node, driver, launch, service, writer, image preset or device activation.

Keep every physical capability false, both velocity limits zero, geometry unmeasured and accepted sensors empty until the corresponding adapter and evidence exist. An empty sensor list means no sensor has been accepted for ROSY here; it does not describe the kit's physical inventory. Do not copy Pinky geometry, servo limits or feedback into this package.

Profile and capability limits are one HWA-003 definition. `core.yaml` is mandatory for model selection and intentionally empty. Native package build/install, product model/profile/capability binding, hardware stopping and actual motion acceptance are separate checks. An absolute operator overlay can still override model-selected paths in existing CORE; this source package does not close that product admission gap.

Before changing runtime behavior, read `docs/reference/robot-compatibility.md`, `docs/plans/2026-10-25-rasptank-multi-robot-design.md`, the owning CORE/driver/Action contracts and relevant existing lessons. Base output remains CORE-owned; joint/action ownership must be integrated through the existing device boundary, never a new raw PWM endpoint in CORE.

Host contracts: `test/test_rasptank_profile.py` exercises real model selection, profile loading, Capability/TaskKind refusal and descriptor absence. Run it through `tools/remote/remote_pytest.py` on the committed revision, not local pytest. This test is not ROS install, Pi boot, image or physical validation.

Completion requires exact tested revision and preserved HOLD states for any unverified native/image/device gates. Record changes in this module's logs and regenerate its index/STATUS through the harness.
