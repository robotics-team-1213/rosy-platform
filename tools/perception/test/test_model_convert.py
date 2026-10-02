"""D-423 §3.3: .pt -> ONNX on the PC only, with a parity check; torch/ultralytics optional."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "tools" / "perception" / "model", ROOT / "tools" / "perception" / "training",
           ROOT / "src" / "runtime" / "sensing"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import convert  # noqa: E402
from control.sensing.perception.learned.manifest import OBJECT_CLASSES, load_manifest  # noqa: E402


def test_module_imports_without_torch_onnx_or_ultralytics():
    """The robot never runs this, and a PC without the ML stack can still read --help."""
    source = (ROOT / "tools" / "perception" / "model" / "convert.py").read_text(encoding="utf-8")
    head = source.split("def ", 1)[0]
    for heavy in ("import torch", "import onnx", "import ultralytics", "from ultralytics"):
        assert heavy not in head
    with pytest.raises(SystemExit) as exit_:
        convert.main(["--help"])
    assert exit_.value.code == 0


def test_parity_is_the_max_abs_difference_over_every_probe():
    ref = lambda x: x * 2.0  # noqa: E731
    near = lambda x: x * 2.0 + 1e-5  # noqa: E731
    far = lambda x: x * 2.5  # noqa: E731
    probes = convert.probe_inputs((1, 3, 32, 32), count=3, seed=0)
    assert len(probes) == 3 and probes[0].dtype == np.float32
    ok = convert.parity(ref, near, probes, tolerance=1e-3)
    assert ok["ok"] and ok["max_abs_diff"] == pytest.approx(1e-5, abs=1e-6)
    assert not convert.parity(ref, far, probes, tolerance=1e-3)["ok"]


def test_parity_refuses_a_shape_change():
    probes = convert.probe_inputs((1, 3, 8, 8), count=1)
    result = convert.parity(lambda x: x, lambda x: x[:, :2], probes, tolerance=1.0)
    assert not result["ok"] and "shape" in result["reason"]


def test_registry_names_the_lane_model_and_refuses_unknown_names():
    assert convert.MODEL_REGISTRY["lane_unet"] == ("rosy_lane_model", "LaneUNet")
    with pytest.raises(ValueError, match="registry"):
        convert.resolve_class("nope")


@pytest.mark.parametrize("argv,word", [
    (["m.pt", "--kind", "state_dict", "--task", "lane_seg"], "--model-class"),
    (["m.pt", "--kind", "ultralytics", "--task", "lane_seg"], "object_det"),
    (["m.pt", "--kind", "torchscript", "--task", "object_det", "--input", "240", "320"], "32"),
    (["m.pt", "--kind", "torchscript", "--task", "lane_seg", "--input", "256", "320",
      "--classes", "c.yaml"], "fixed"),
])
def test_cli_refuses_combinations_before_loading_anything(tmp_path, capsys, argv, word):
    common = ["--out", str(tmp_path / "o"), "--dataset-repo", "r", "--dataset-revision", "a" * 40,
              "--camera-profile-revision", "cam-1", "--trainer", "t"]
    assert convert.main(argv + common) == 2
    assert word in capsys.readouterr().err


def test_object_manifest_is_the_robot_contract(tmp_path):
    onnx_path = tmp_path / "staged.onnx"
    onnx_path.write_bytes(b"onnx-bytes")
    doc = convert.write_object_manifest(
        tmp_path / "out", onnx_path=onnx_path, input_hw=(256, 320), color="rgb", scale=1 / 255,
        mean=[0, 0, 0], std=[1, 1, 1], dataset_repo="org/d", dataset_revision="a" * 40,
        camera_profile_revision="cam-1", trainer="colab:yolo", precision="fp32",
        metrics={"export_parity_max_abs_diff": 1e-6}, date="20261003")
    m = load_manifest(tmp_path / "out")
    assert m.task == "object_det" and [c.name for c in m.classes] == list(OBJECT_CLASSES)
    sha = hashlib.sha256(b"onnx-bytes").hexdigest()
    assert doc["model_revision"] == f"object-det-20261003-{sha[:8]}"
    assert json.loads((tmp_path / "out" / "model_manifest.json").read_text())["metrics"] == {
        "export_parity_max_abs_diff": 1e-6}


def _synthetic_detector(path, h=64, w=64, anchors=12):
    """[1, 3, H, W] -> [1, 4 + C, A]: a fixed linear map, enough for parity and the runtime."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    c = 4 + len(OBJECT_CLASSES)
    weight = np.linspace(-1, 1, 3 * h * w * c * anchors // (h * w), dtype=np.float32)
    nodes = [helper.make_node("ReduceMean", ["x"], ["m"], axes=[2, 3], keepdims=0),
             helper.make_node("MatMul", ["m", "w"], ["y0"]),
             helper.make_node("Reshape", ["y0", "shape"], ["y"])]
    graph = helper.make_graph(
        nodes, "det", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, h, w])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, c, anchors])],
        [helper.make_tensor("w", TensorProto.FLOAT, [3, c * anchors], weight),
         helper.make_tensor("shape", TensorProto.INT64, [3], [1, c, anchors])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, path)
    return weight.reshape(3, c * anchors), c, anchors


def test_synthetic_onnx_parity_against_its_numpy_reference(tmp_path):
    pytest.importorskip("onnxruntime")
    path = tmp_path / "det.onnx"
    weight, c, anchors = _synthetic_detector(path)
    reference = lambda x: (x.mean(axis=(2, 3)) @ weight).reshape(1, c, anchors)  # noqa: E731
    result = convert.parity(reference, convert.onnx_runner(path),
                            convert.probe_inputs((1, 3, 64, 64), count=2), tolerance=1e-4)
    assert result["ok"], result


def test_torchscript_export_when_torch_is_present(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("onnxruntime")

    class Tiny(torch.nn.Module):
        def forward(self, x):
            return torch.nn.functional.conv2d(x, torch.ones(2, 3, 1, 1))

    scripted = tmp_path / "tiny.pt"
    torch.jit.script(Tiny()).save(str(scripted))
    model = convert.load_torch_model(scripted, "torchscript")
    out = tmp_path / "tiny.onnx"
    convert.export_torch(model, out, (1, 3, 32, 32))
    result = convert.parity(convert.torch_runner(model), convert.onnx_runner(out),
                            convert.probe_inputs((1, 3, 32, 32), count=2), tolerance=1e-4)
    assert result["ok"], result
