"""D-431: CPU adapter, one preprocessing pass, and real NCNN extraction."""

import hashlib
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from control.sensing.perception.learned.manifest import ManifestError, load_manifest
from test_learned_manifest_ncnn import ncnn_doc, write_doc


def adapter():
    from control.sensing.perception.learned.ncnn_session import NcnnSession
    return NcnnSession


class Net:
    def __init__(self):
        self.opt = SimpleNamespace()
        self.rc = 0
        self.output = np.ones((10, 4), np.float32)

    def load_param(self, path):
        return self.rc

    def load_model(self, path):
        return self.rc

    def input_names(self):
        return ["in0"]

    def output_names(self):
        return ["out0"]

    def create_extractor(self):
        return self

    def input(self, name, value):
        self.received = name, value
        return self.rc

    def extract(self, name):
        return self.rc, self.output


def test_adapter_keeps_preprocessed_channels_and_checks_extraction(tmp_path, monkeypatch):
    net = Net()
    monkeypatch.setitem(sys.modules, "ncnn", SimpleNamespace(Net=lambda: net, Mat=lambda x: x.copy()))
    m = load_manifest(write_doc(tmp_path, ncnn_doc()))
    session = adapter()(m, 2)
    x = np.zeros(m.input.shape, np.float32)
    x[:, 0], x[:, 1], x[:, 2] = .1, .2, .3
    y = session.run(x)
    assert np.array_equal(net.received[1], x[0])
    assert y.shape == (1, 10, 4)
    assert net.opt.num_threads == 2 and not net.opt.use_vulkan_compute
    assert not net.opt.use_fp16_arithmetic and not net.opt.use_fp16_storage
    net.rc = -1
    with pytest.raises(ManifestError, match="input"):
        session.run(x)
    net.rc = 0
    net.output[0, 0] = np.nan
    with pytest.raises(ManifestError, match="finite"):
        session.run(x)


def test_load_failure_and_wrong_input_refused(tmp_path, monkeypatch):
    net = Net()
    net.rc = -100
    monkeypatch.setitem(sys.modules, "ncnn", SimpleNamespace(Net=lambda: net, Mat=lambda x: x))
    m = load_manifest(write_doc(tmp_path, ncnn_doc()))
    with pytest.raises(ManifestError, match="load_param"):
        adapter()(m, 2)
    net.rc = 0
    session = adapter()(m, 2)
    for bad in (np.zeros((3, 32, 32), np.float32), np.zeros(m.input.shape, np.float64)):
        with pytest.raises(ManifestError, match="input"):
            session.run(bad)


def test_real_ncnn_convolution_preserves_chw_and_output_axes(tmp_path):
    pytest.importorskip("ncnn")
    param = ("7767517\n3 3\nInput in 0 1 in0\n"
             "Convolution conv 1 1 in0 features 0=10 1=1 5=0 6=30\n"
             "Reshape reshape 1 1 features out0 0=1024 1=10\n").encode()
    weights = b"\x00\x00\x00\x00" + np.tile([1., 2., 3.], 10).astype('<f4').tobytes()
    doc = ncnn_doc()
    doc["input"]["shape"] = [1, 3, 32, 32]
    for name, data in (("model.param", param), ("model.bin", weights)):
        (tmp_path / name).write_bytes(data)
        next(f for f in doc["files"] if f["name"] == name)["sha256"] = hashlib.sha256(data).hexdigest()
    m = load_manifest(write_doc(tmp_path, doc))
    session = adapter()(m, 2)
    x = np.random.default_rng(0).random(m.input.shape, dtype=np.float32)
    y = session.run(x)
    expected = (x[0, 0] + 2 * x[0, 1] + 3 * x[0, 2]).reshape(1, -1)
    assert np.allclose(y[0], np.repeat(expected, 10, axis=0), atol=1e-6)
