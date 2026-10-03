"""D-431 T7: separately verified TorchScript lane conversion through PNNX, not YOLO."""

import importlib.metadata
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from compare_backends import compare_lane_frames
from export_ncnn import bundle, publish
from control.sensing.perception.learned.manifest import load_manifest
from control.sensing.perception.learned.ncnn_session import NcnnSession


def convert_lane_ncnn(args, hw, out):
    import pnnx
    from convert import load_torch_model, parity, probe_inputs, torch_runner
    root = Path(os.environ.get("ROSY_MODEL_SCRATCH", "X:/DevTemp/rosy-model-export" if os.name == "nt"
                               else tempfile.gettempdir()))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lane-ncnn-", dir=root) as scratch:
        staging = Path(scratch)
        source = staging / "source.pt"
        shutil.copyfile(args.source, source)
        model = load_torch_model(source, "torchscript")
        result = subprocess.run([pnnx.EXEC_PATH, str(source), f"inputshape=[1,3,{hw[0]},{hw[1]}]", "fp16=0"],
                                capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise ValueError(f"PNNX lane conversion failed: {result.stderr[-2000:]}")
        folder = staging / "bundle"
        folder.mkdir()
        doc = bundle(folder, staging, args=args, hw=hw, family="lane_torchscript",
                     exporter_version=importlib.metadata.version("pnnx"))
        session = NcnnSession(load_manifest(folder))
        reference = torch_runner(model)
        probes = parity(reference, session.run, probe_inputs((1, 3, *hw)), args.tolerance, args.rtol)
        if not probes["ok"]:
            raise ValueError(f"NCNN lane probe parity failed: {probes}")
        frames = sorted(p for p in Path(args.frames).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
        if len(frames) < args.min_eval_frames:
            raise ValueError(f"need at least {args.min_eval_frames} readable evaluation frames")
        report = compare_lane_frames(reference, session.run, load_manifest(folder), frames,
                                     atol=args.tolerance, rtol=args.rtol,
                                     min_pixel_agreement=args.min_pixel_agreement)
        report["min_eval_frames"] = args.min_eval_frames
        return publish(folder, doc, report, probes, out)
