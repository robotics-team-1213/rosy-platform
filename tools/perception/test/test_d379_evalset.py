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


def test_exclude_eval_needs_an_eval_manifest(tmp_path):
    a = _labels_dir(tmp_path, "s1", [(L.FLOOR, False)])
    b = _labels_dir(tmp_path, "s2", [(L.FLOOR, False)])
    _, ds = build.build_auto_dataset([a, b], tmp_path / "store", "lanes")
    with pytest.raises(build.BuildError, match="not an eval set"):
        build.build_auto_dataset([a, b], tmp_path / "store", "x", exclude_eval=[ds])
    with pytest.raises(build.BuildError, match="no readable manifest"):
        build.build_auto_dataset([a, b], tmp_path / "store", "x", exclude_eval=[tmp_path / "nope"])


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
