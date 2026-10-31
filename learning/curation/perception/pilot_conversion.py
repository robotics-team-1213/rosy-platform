"""Stage a Pilot conversion before publishing; retain interrupted output bytes."""
import json
import os
import sys
import tempfile
from pathlib import Path


def default_convert(folder: Path, out: Path, codec: str) -> tuple[int, Path | None]:
    import bag_to_video
    meta_path = folder / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    stem = bag_to_video.output_stem(folder, meta)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{stem}-", dir=out) as temporary:
        stage = Path(temporary)
        try:
            rc = bag_to_video.main([str(folder), "--out", str(stage), "--codec", codec])
        except SystemExit as exc:
            print(f"{folder.name}: bag_to_video: {exc}", file=sys.stderr)
            return 1, None
        if rc != 0:
            return rc, None
        # Publish the sidecar last so an interrupted publication cannot look complete.
        outputs = [stage / f"{stem}{ext}" for ext in (".mp4", ".json", ".scan.npz", ".jsonl")]
        if not all((stage / f"{stem}{ext}").is_file() for ext in (".mp4", ".jsonl", ".json")):
            return 1, None
        old = [out / p.name for p in outputs if (out / p.name).exists()]
        if old:
            backup = Path(tempfile.mkdtemp(prefix=f".{stem}-interrupted-", dir=out))
            for path in old:
                os.rename(path, backup / path.name)
            print(f"{folder.name}: previous conversion files preserved in {backup}")
        for path in outputs:
            if path.is_file():
                os.rename(path, out / path.name)
    return 0, out / f"{stem}.jsonl"
