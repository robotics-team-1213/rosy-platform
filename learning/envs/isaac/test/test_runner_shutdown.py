"""A failed SDK initialization must not be hidden by Kit's default exit(0)."""

import builtins
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("runner", ["run_rosy", "import_omx"])
@pytest.mark.parametrize("headless", [True, False])
def test_sdk_error_survives_runner_cleanup(runner, headless, tmp_path, monkeypatch):
    directory = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(runner, directory / f"{runner}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    urdf = tmp_path / "model.urdf"
    urdf.write_text('<robot><joint name="caster_rotate_joint" type="continuous"/>'
                    '<joint name="caster_wheel_joint" type="continuous"/></robot>')
    monkeypatch.setenv("ROS_DOMAIN_ID", "139")
    monkeypatch.setattr(module, "parse_args", lambda: SimpleNamespace(
        namespace="rosy_99", model="omx_f", urdf=urdf, output_dir=tmp_path / "output",
        headless=headless, frames=1, wheel_damping=None))
    monkeypatch.setattr(module, "check_urdf", lambda *a, **k: None)
    if runner == "import_omx":
        monkeypatch.setattr(module, "check_vendor_manifest", lambda: None)
    monkeypatch.setattr(module, "validate_output_path", lambda path: path)
    captured = {}

    class App:
        def __init__(self, config):
            captured.update(config)

        def close(self):
            # NVIDIA documents immediate process exit as the default. Represent
            # it as SystemExit so this regression can run without killing pytest.
            if captured.get("fast_shutdown", True):
                raise SystemExit(0)
            captured["closed"] = True

    monkeypatch.setitem(sys.modules, "isaacsim", SimpleNamespace(SimulationApp=App))
    manager = SimpleNamespace(set_extension_enabled_immediate=lambda *args: None,
                              is_extension_enabled=lambda name: False)
    monkeypatch.setitem(sys.modules, 'omni.kit.app', SimpleNamespace(
        get_app=lambda: SimpleNamespace(get_extension_manager=lambda: manager)))
    original_import = builtins.__import__

    def failing_sdk_import(name, *args, **kwargs):
        if name in ("omni.graph.core", "omni.kit.app"):
            raise RuntimeError("SDK initialization failed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_sdk_import)
    with pytest.raises(RuntimeError, match="SDK initialization failed"):
        module.main()
    assert captured["closed"] is True
    assert captured["fast_shutdown"] is False
    if runner == "run_rosy" and headless:
        assert (captured["width"], captured["height"], captured["anti_aliasing"]) == (640, 480, 0)
        assert captured["extra_args"] == ['--/app/extensions/excluded=["isaacsim.gui.menu"]']
    else:
        assert not {"width", "height", "anti_aliasing"}.intersection(captured)
