"""D-431: CPU NCNN session accepting already-preprocessed float32 NCHW input."""

from __future__ import annotations

import numpy as np

from .manifest import ManifestError, ModelManifest
from .runner import add_learned_site


class NcnnSession:
    def __init__(self, manifest: ModelManifest, threads: int = 2):
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise ManifestError("threads must be a positive integer")
        param, weights = manifest.ncnn_files()
        add_learned_site()
        import ncnn  # optional: the base sensing package never requires this import

        self._ncnn = ncnn
        self._shape = manifest.input.shape
        self._task = manifest.task
        self._channels = (4 if self._task == "object_det" else 0) + len(manifest.classes)
        self._net = ncnn.Net()
        options = self._net.opt
        options.num_threads = threads
        options.use_vulkan_compute = False
        options.use_fp16_packed = False
        options.use_fp16_storage = False
        options.use_fp16_arithmetic = False
        options.use_bf16_storage = False
        for operation, path in (("load_param", param), ("load_model", weights)):
            if getattr(self._net, operation)(str(path)) != 0:
                raise ManifestError(f"ncnn {operation} failed for {path.name}")
        runtime = manifest.raw["runtime"]
        self._input, self._output = runtime["input_blob"], runtime["output_blob"]
        if tuple(self._net.input_names()) != (self._input,) or tuple(self._net.output_names()) != (self._output,):
            raise ManifestError("ncnn blob names differ from the single-input/single-output contract")

    def run(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)
        if x.shape != self._shape or x.dtype != np.float32 or not np.isfinite(x).all():
            raise ManifestError(f"ncnn input: expected finite float32 {self._shape}")
        # NCNN owns a CHW Mat view; keep its numpy backing alive until extract finishes.
        chw = np.ascontiguousarray(x[0])
        tensor = self._ncnn.Mat(chw)
        extractor = self._net.create_extractor()
        if extractor.input(self._input, tensor) != 0:
            raise ManifestError("ncnn input failed")
        rc, output = extractor.extract(self._output)
        if rc != 0:
            raise ManifestError("ncnn extract failed")
        result = np.array(output, dtype=np.float32, copy=True)
        if self._task == "object_det":
            valid = result.ndim == 2 and result.shape[0] == self._channels and result.shape[1] > 0
            expected = f"({self._channels}, A)"
        else:
            expected = (self._channels, *self._shape[2:])
            valid = result.shape == expected
        if not valid:
            raise ManifestError(f"ncnn output shape {result.shape}: expected {expected}")
        if not np.isfinite(result).all():
            raise ManifestError("ncnn output is not finite")
        return result[None]
