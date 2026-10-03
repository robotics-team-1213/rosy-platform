"""Hand a trained model over to the site: drop it into the store inbox (D-373 decision 8).

    package(model_folder, inbox_dir)  -> inbox_dir/<model_revision>__<utc>/ with READY last
    package_zip(model_folder, zip)    -> the same folder inside a zip, for download

Only model_manifest.json and the files it names are handed over. READY holds the
folder's content_sha (store.py) and is written after every other file, so the site
watcher never takes a half-copied or half-synced folder. The zip is for a trainer
without the store mounted: unzip it into models/inbox/ as it is.

Stdlib only (plus learning/training/perception/store.py): runs in Colab and on any PC."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

_PERCEPTION = Path(__file__).resolve().parents[1]
if str(_PERCEPTION) not in sys.path:
    sys.path.insert(0, str(_PERCEPTION))

import store  # noqa: E402

MANIFEST_NAME = "model_manifest.json"


def _files(model_folder: Path) -> tuple[str, list[str]]:
    doc = json.loads((model_folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    rev = doc.get("model_revision")
    if not store.safe_name(rev):
        raise ValueError(f"model_revision {rev!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
    names = [f["name"] for f in doc.get("files") or []]
    for name in names:
        if not isinstance(name, str) or Path(name).name != name or not store.safe_name(name):
            raise ValueError(f"files: bad name {name!r}")
        if not (model_folder / name).is_file():
            raise FileNotFoundError(f"{name} named in the manifest is missing")
    return rev, [MANIFEST_NAME, *names]


def _utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def package(model_folder, inbox_dir) -> Path:
    model_folder = Path(model_folder)
    rev, names = _files(model_folder)
    dest = Path(inbox_dir) / f"{rev}__{_utc()}"
    dest.mkdir(parents=True, exist_ok=False)
    for name in names:
        shutil.copy2(model_folder / name, dest / name)
    (dest / store.READY).write_text(store.content_sha(dest), encoding="utf-8")
    print(f"handed over: {dest}")
    return dest


def package_zip(model_folder, zip_path) -> Path:
    zip_path = Path(zip_path)
    with tempfile.TemporaryDirectory() as tmp:
        folder = package(model_folder, tmp)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.iterdir()):
                z.write(p, f"{folder.name}/{p.name}")
    print(f"zip: {zip_path} (unzip into <store>/models/inbox/)")
    return zip_path


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: handover.py <model_folder> <inbox_dir | out.zip>", file=sys.stderr)
        sys.exit(2)
    target = sys.argv[2]
    (package_zip if target.endswith(".zip") else package)(sys.argv[1], target)
