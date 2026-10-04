"""Offline review packs bind drafts to original bytes without granting approval."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'dataset' / 'review_pack.py'
spec = importlib.util.spec_from_file_location('review_pack', MODULE)
review_pack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_pack)


def fixture_pack(tmp_path):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'object-images').mkdir()
    (source / 'frames').mkdir()
    data = cv2.imencode('.jpg', np.zeros((24, 32, 3), dtype=np.uint8))[1].tobytes()
    digest = hashlib.sha256(data).hexdigest()
    (source / 'object-images/a.jpg').write_bytes(data)
    (source / 'frames/000000.jpg').write_bytes(data)
    object_row = {'video': '</script><script>bad</script>', 'video_frame': 7,
                  'image': 'object-images/a.jpg', 'image_sha256': digest,
                  'review_status': 'approved', 'complete_frame_review': True,
                  'boxes': [{'label': 'traffic_light', 'bbox_xyxy': [2, 3, 8, 10]}]}
    (source / 'object-drafts.jsonl').write_text(json.dumps(object_row) + '\n', encoding='utf-8')
    frame = {'index': 0, 'image_sha256': digest, 'width': 32, 'height': 24}
    (source / 'frames.jsonl').write_text(json.dumps(frame) + '\n', encoding='utf-8')
    return source, data


def test_bound_original_bytes_pending_and_escaped_metadata(tmp_path):
    source, data = fixture_pack(tmp_path)
    out = tmp_path / 'out'
    result = review_pack.build_review(source, out)
    assert result['verified_original_images'] == 2
    assert result['human_approved_frames'] == 0
    assert (out / 'object-images/a.jpg').read_bytes() == data
    row = json.loads((out / 'object-source.jsonl').read_text())
    assert row['review_status'] == 'pending_human'
    assert row['complete_frame_review'] is False
    assert row['boxes'][0]['signal_state'] == 'unknown'
    page = (out / 'review.html').read_text(encoding='utf-8')
    assert '</script><script>bad' not in page
    assert 'data:image/jpeg;base64,' in page
    assert 'function exportRows()' in page
    assert 'canvas.onpointerup' in page
    assert '<script src=' not in page
    with pytest.raises(FileExistsError):
        review_pack.build_review(source, out)


def test_corrupted_object_image_refused_before_output(tmp_path):
    source, _ = fixture_pack(tmp_path)
    (source / 'object-images/a.jpg').write_bytes(b'changed')
    out = tmp_path / 'out'
    with pytest.raises(ValueError, match='hash mismatch'):
        review_pack.build_review(source, out)
    assert not out.exists()


def test_gallery_hash_and_dimensions_checked(tmp_path):
    source, _ = fixture_pack(tmp_path)
    frame = json.loads((source / 'frames.jsonl').read_text())
    frame['width'] = 100
    (source / 'frames.jsonl').write_text(json.dumps(frame), encoding='utf-8')
    with pytest.raises(ValueError, match='dimensions'):
        review_pack.build_review(source, tmp_path / 'out')


def test_path_escape_refused(tmp_path):
    with pytest.raises(ValueError, match='within source root'):
        review_pack._image(tmp_path / 'source', '../other.jpg', 'a' * 64)


def test_traversal_reentering_source_is_rejected(tmp_path):
    source, data = fixture_pack(tmp_path)
    with pytest.raises(ValueError, match='within source root'):
        review_pack._image(source, '../source/object-images/a.jpg', hashlib.sha256(data).hexdigest())


def test_preview_classes_match_export_contract():
    root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(root / 'src' / 'runtime' / 'sensing'))
    sys.path.insert(0, str(root / 'src' / 'contracts' / 'foundation'))
    from control.sensing.perception.learned.manifest import OBJECT_CLASSES
    assert review_pack.CLASSES == OBJECT_CLASSES
