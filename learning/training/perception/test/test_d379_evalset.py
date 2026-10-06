"""D-379 decision 3: a fixed eval set in the store, disjoint from training builds."""
import json
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
_PERCEPTION = str(Path(__file__).resolve().parents[1])
if _PERCEPTION not in sys.path:
    sys.path.insert(0, _PERCEPTION)

import build  # noqa: E402
import labels as L  # noqa: E402
import store  # noqa: E402
from test_d379_catalog_and_store import _labels_dir  # noqa: E402


def _with_sources(d, sources_by_index):
    jl = d / "labels.jsonl"
    rows = [json.loads(line) for line in jl.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        r["sources"] = sources_by_index.get(r["index"], r["sources"])
    jl.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return d


def _eval_set(tmp_path, session="20261001T090000Z_e"):
    d = _with_sources(_labels_dir(tmp_path, session, [(L.FLOOR, False)] * 3),
                      {1: ["trajectory"], 2: []})
    return build.build_auto_dataset([d], tmp_path / "store", "evalA", eval_set=True)


def test_eval_set_layout_split_purpose_and_trusted_sources(tmp_path):
    manifest, final = _eval_set(tmp_path)
    assert final.parent == tmp_path / "store" / "evalsets" / "evalA"
    assert final.name == store.content_sha(final) == build.content_sha(final)
    assert manifest["purpose"] == "eval" and manifest["schema"] == build.SCHEMA
    assert manifest["trusted_sources"] == ["lidar", "trajectory"]
    # D-373: the wall channel must survive export as a wall role, so device
    # postprocessing can distinguish wall evidence from ignored crosswalks.
    assert {c["name"]: c["role"] for c in manifest["classes"]}["wall"] == "wall"
    assert {f["split"] for f in manifest["frames"]} == {"eval"}
    assert [f["image"].rsplit("__", 1)[1] for f in manifest["frames"]] == ["000000.jpg", "000001.jpg"]
    (gone,) = manifest["excluded"]
    assert gone["frame"] == "20261001T090000Z_e__000002"
    assert gone["reason"].startswith("no trusted label source")
    assert store.Store(tmp_path / "store").evalsets() == {"evalA": [final.name]}
    assert store.Store(tmp_path / "store").status()["evalsets"] == {"evalA": [final.name]}
    # same inputs: same version folder, nothing rewritten
    _, again = build.build_auto_dataset([tmp_path / "labels" / "20261001T090000Z_e"],
                                        tmp_path / "store", "evalA", eval_set=True)
    assert again == final and [p.name for p in final.parent.iterdir()] == [final.name]


def test_eval_set_with_no_trusted_frame_is_refused(tmp_path):
    d = _with_sources(_labels_dir(tmp_path, "s_e", [(L.FLOOR, False)]), {0: ["rule"]})
    with pytest.raises(build.BuildError, match="no frame left"):
        build.build_auto_dataset([d], tmp_path / "store", "e", eval_set=True)
    left = tmp_path / "store" / "evalsets" / "e"
    assert not left.exists() or not any(left.iterdir())


def test_training_build_refuses_an_eval_session_and_records_disjointness(tmp_path):
    _, ev = _eval_set(tmp_path)
    a = _labels_dir(tmp_path, "20260930T124745Z_d", [(L.FLOOR, False)])
    b = _labels_dir(tmp_path, "20260930T133221Z_d", [(L.FLOOR, False)])
    manifest, final = build.build_auto_dataset([a, b], tmp_path / "store", "lanes", exclude_eval=[ev])
    assert manifest["disjoint_from"] == [{"name": "evalA", "content_sha": ev.name}]
    assert final.parent.parent.name == "datasets"
    # the eval session itself as training input
    with pytest.raises(build.BuildError, match=r"20261001T090000Z_e.*evalA@" + ev.name):
        build.build_auto_dataset([a, tmp_path / "labels" / "20261001T090000Z_e"], tmp_path / "st2",
                                 "lanes", exclude_eval=[ev])
    # no exclusion given: no disjoint_from key (manifests of earlier builds unchanged)
    plain, _ = build.build_auto_dataset([a, b], tmp_path / "st3", "lanes")
    assert "disjoint_from" not in plain


def test_reserved_eval_source_blocks_training_before_eval_version_exists(tmp_path):
    st = store.Store(tmp_path / "store")
    st.reserve_eval_source("heldout", "shared-group")
    assert st.evalsets() == {}
    a = _labels_dir(tmp_path, "heldout", [(L.FLOOR, False)])
    with pytest.raises(build.BuildError, match="reserved eval"):
        build.build_auto_dataset([a], st.root, "lanes")
    with pytest.raises(store.StoreError, match="already reserved"):
        st.reserve_eval_source("heldout", "different-group")
    reservation = next(next((st.root / "eval-reservations").iterdir()).iterdir())
    reservation.write_text("{}")
    with pytest.raises(store.StoreError, match="reservation"):
        st.eval_reservations()


def test_reserved_group_blocks_other_session_and_unknown_group(tmp_path):
    st = store.Store(tmp_path / "store")
    st.reserve_eval_source("heldout", "shared-group")
    a = _labels_dir(tmp_path, "other", [(L.FLOOR, False)])
    with pytest.raises(build.BuildError, match="group unknown"):
        build.build_auto_dataset([a], st.root, "lanes")
    meta_path = a / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["capture_group"] = "shared-group"
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(build.BuildError, match="reserved eval"):
        build.build_auto_dataset([a], st.root, "lanes")
    meta["capture_group"] = "separate-group"
    meta_path.write_text(json.dumps(meta))
    b = _labels_dir(tmp_path, "another", [(L.FLOOR, False)])
    second = b / "meta.json"
    second_meta = json.loads(second.read_text())
    second_meta["capture_group"] = "another-group"
    second.write_text(json.dumps(second_meta))
    manifest, _ = build.build_auto_dataset([a, b], st.root, "lanes")
    assert {row["capture_group"] for row in manifest["frames"]} == {"separate-group", "another-group"}


def test_exclude_eval_needs_an_eval_manifest(tmp_path):
    a = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    b = _labels_dir(tmp_path, "s2", [(L.FLOOR, False)])
    _, ds = build.build_auto_dataset([a, b], tmp_path / "store", "lanes")
    with pytest.raises(build.BuildError, match="not an eval set"):
        build.build_auto_dataset([a, b], tmp_path / "store", "x", exclude_eval=[ds])
    with pytest.raises(build.BuildError, match="no readable manifest"):
        build.build_auto_dataset([a, b], tmp_path / "store", "x", exclude_eval=[tmp_path / "nope"])


@pytest.mark.parametrize("target", ["manifest", "image", "mask", "extra"])
def test_exclude_eval_refuses_changed_fixed_evaluation(tmp_path, target):
    _, ev = _eval_set(tmp_path)
    if target == "manifest":
        path = ev / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["frames"] = []
        manifest["labels"] = []
        path.write_text(json.dumps(manifest))
    elif target == "extra":
        (ev / "unexpected.txt").write_text("not part of the fixed version")
    else:
        path = next((ev / ("images" if target == "image" else "masks")).rglob("*.*"))
        path.write_bytes(b"changed content")
    with pytest.raises(build.BuildError, match="content hash"):
        build.read_eval_set(ev)


def test_cvat_build_refuses_modified_eval_before_writing_training_outputs(tmp_path):
    from test_dataset_build import CLASSES, _export, _frames_dir, _mask
    _, ev = _eval_set(tmp_path, session="s1")
    manifest = json.loads((ev / "manifest.json").read_text())
    manifest["frames"] = []
    manifest["labels"] = []
    (ev / "manifest.json").write_text(json.dumps(manifest))
    a = _frames_dir(tmp_path / "f", "s1", [0])
    b = _frames_dir(tmp_path / "f", "s2", [0])
    exp = _export(tmp_path, {"s1__000000": _mask(), "s2__000000": _mask()})
    out = tmp_path / "dataset"
    with pytest.raises(build.BuildError, match="content hash"):
        build.build_dataset(exp, [a, b], CLASSES, out, exclude_eval=[ev])
    assert not out.exists()


def test_manifest_cannot_change_between_parsing_and_content_hash(tmp_path, monkeypatch):
    _, ev = _eval_set(tmp_path)
    real_hash = build.content_sha

    def mutate_after_hash(folder, **kwargs):
        digest = real_hash(folder, **kwargs)
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["frames"] = []
        manifest["labels"] = []
        path.write_text(json.dumps(manifest))
        return digest

    monkeypatch.setattr(build, "content_sha", mutate_after_hash)
    with pytest.raises(build.BuildError, match="content hash"):
        build.read_eval_set(ev)


def test_parsed_manifest_is_part_of_the_verified_digest_despite_aba(tmp_path, monkeypatch):
    _, ev = _eval_set(tmp_path)
    path = ev / "manifest.json"
    original = path.read_bytes()
    changed = json.loads(original)
    changed["frames"] = []
    changed["labels"] = []
    altered = json.dumps(changed).encode()
    path.write_bytes(altered)
    real_hash = build.content_sha

    def restore_original_only_during_hash(folder, **kwargs):
        path.write_bytes(original)
        try:
            return real_hash(folder, **kwargs)
        finally:
            path.write_bytes(altered)

    monkeypatch.setattr(build, "content_sha", restore_original_only_during_hash)
    with pytest.raises(build.BuildError, match="content hash"):
        build.read_eval_set(ev)


def test_cli_eval_set_and_exclude(tmp_path, capsys):
    e = _labels_dir(tmp_path, "s_eval", [(L.FLOOR, False)])
    st = tmp_path / "store"
    assert build.main(["--auto-labels", str(e), "--store", str(st), "--name", "ev", "--eval-set"]) == 0
    (ev,) = (st / "evalsets" / "ev").iterdir()
    a = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    assert build.main(["--auto-labels", str(a), str(e), "--store", str(st), "--name", "tr",
                       "--exclude-eval", str(ev)]) == 1
    assert "training and eval must be disjoint" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        build.main(["--auto-labels", str(a), "--store", str(st), "--name", "x", "--eval-set",
                    "--exclude-eval", str(ev)])
    assert sorted(p.name for p in st.iterdir()) == ["evalsets"]


def test_cvat_build_refuses_an_eval_session(tmp_path):
    from test_dataset_build import CLASSES, _export, _frames_dir, _mask
    e = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    _, ev = build.build_auto_dataset([e], tmp_path / "store", "ev", eval_set=True)
    a = _frames_dir(tmp_path / "f", "s1", [0])
    b = _frames_dir(tmp_path / "f", "s2", [0])
    exp = _export(tmp_path, {"s1__000000": _mask(), "s2__000000": _mask()})
    with pytest.raises(build.BuildError, match=r"\['s1'\].*training and eval must be disjoint"):
        build.build_dataset(exp, [a, b], CLASSES, tmp_path / "ds", exclude_eval=[ev])
    c = _frames_dir(tmp_path / "f", "s3", [0])
    exp2 = tmp_path / "exp2"
    exp.rename(exp2)
    exp = _export(tmp_path, {"s2__000000": _mask(), "s3__000000": _mask()})
    m = build.build_dataset(exp, [b, c], CLASSES, tmp_path / "ds2", exclude_eval=[ev])
    assert m["disjoint_from"] == [{"name": "ev", "content_sha": ev.name}]
