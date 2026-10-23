"""D-436 full CI suite catalog and documented exclusions."""

CI_FULL_MATRIX = (
    {"name": "learning-policy", "invocations": [
        ["learning/registry/policy/test"], ["learning/training/omx/test"], ["learning/training/pinky/test"],
        ["learning/curation/omx/test"], ["learning/curation/pinky/test"],
        ["learning/training/world_model/test"], ["learning/evaluation/world_model/test"],
        ["operations/prediction/world_model/test"]], "ros": "none"},
    {"name": "core-domain", "invocations": [[
        "middleware/core/gateway/test", "middleware/core/events/test", "middleware/core/services/test",
        "shared/web/test", "contracts/foundation/test",
        "middleware/devices/pinky/profile/test", "middleware/devices/omx/profile/test"], [
        "middleware/core/gateway/test/test_account_pipeline.py"
    ]], "ros": "none"},
    # Never ran in CI before D-436 (D-191 follow-up); reports until its first green run.
    {"name": "sensing", "invocations": [["middleware/perception/test"]], "ros": "none", "gating": False},
    {"name": "fleet", "invocations": [["operations/fleet/test"]], "ros": "none"},
    {"name": "site-vision-cell", "invocations": [
        ["operations/overhead/test"], ["operations/processes/cell/test"], ["operations/situation/test"],
        ["operations/world/test"],
        ["test/test_platform_palletizing_compat.py", "test/test_platform_cell_submission.py",
         "test/architecture/test_platform_dependency_boundaries.py"]], "ros": "none"},
    {"name": "gz-sim", "invocations": [["integrations/simulation/gazebo/test"]], "ros": "overlay"},
    {"name": "hardware-safety", "invocations": [[
        "middleware/devices/pinky/bringup/test", "middleware/drivers/pinky_adc/test",
        "middleware/perception/test/test_ir_adc_lock.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_flake8.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_pep257.py",
        "--ignore=middleware/devices/pinky/bringup/test/test_copyright.py"]], "ros": "base"},
)
# D-762 stage 1: the only registered test files CI's full tier skips, each with its reason.
# Every other registered module suite CI_FULL_MATRIX does not name runs on the `modules` runner.
CI_FULL_EXCLUDED = {
    f"middleware/devices/pinky/bringup/test/test_{name}.py":
        "ament lint template, not a product contract; CI never ran it and the lab full tier --ignores it too"
    for name in ("flake8", "pep257", "copyright")
}
