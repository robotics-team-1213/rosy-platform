"""Human snapshots may train without changing original collection decisions."""
import copy
import hashlib
import json
import uuid

import pytest

from test_experiment_export import prepared
from test_experiment_native import capture
from test_native_cycle import module, splits


def reviewed(prepared):
    from experiment_reviews import canonical, source_revision
    export, root, row, body = prepared
    decisions = json.loads((root/'decisions.json').read_bytes())
    original = copy.deepcopy(decisions)
    for decision in original:
        decision.update(outcome='unknown', split='exclude', reviewer='', reason='')
    (root/'decisions.json').write_text(json.dumps(original))
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
              for name in export.pipeline.PREPARED_FILES}
    files = export.native.dataset_files(root)
    review = dict(id=str(uuid.uuid4()), source_revision=source_revision(hashes, files),
                  decisions=decisions, sha256=hashlib.sha256(canonical(decisions)).hexdigest(),
                  reviewer_identity={'kind': 'local_unverified', 'id': 'operator'})
    return export, root, row, body, review


def test_review_snapshot_reaches_converter_without_overwriting_unknown_originals(prepared, tmp_path, monkeypatch):
    export, root, row, body, review = reviewed(prepared)
    with pytest.raises(ValueError):
        export.prepare_export(body, row)
    request, fields = export.prepare_export(body, row, review=review)
    assert request['review'] == review and fields['review_id'] == review['id']
    originals = {name: (root/name).read_bytes() for name in export.pipeline.PREPARED_FILES}
    output = tmp_path/'run'
    calls = []
    def convert(actual, decisions, profile, destination):
        assert actual == root and decisions == output/'reviewed-decisions.json'
        assert json.loads(decisions.read_bytes()) == review['decisions']
        calls.append(destination)
        destination.mkdir()
        return {'dataset_revision': 'a'*64}
    monkeypatch.setattr(export.pipeline, 'export_experiment', convert)
    result = export.run_export(request, output)
    assert calls == [output/'export'] and result['review_id'] == review['id']
    assert all((root/name).read_bytes() == raw for name, raw in originals.items())


@pytest.mark.parametrize('fault', ['decisions', 'source_revision', 'source_after_admission'])
def test_snapshot_identity_or_source_changes_cannot_fall_back_to_originals(prepared, tmp_path, monkeypatch, fault):
    export, root, row, body, review = reviewed(prepared)
    if fault == 'decisions':
        review['decisions'][0]['reason'] = 'changed without matching snapshot hash'
    elif fault == 'source_revision':
        review['source_revision'] = '0'*64
    if fault != 'source_after_admission':
        with pytest.raises(ValueError, match='review|snapshot'):
            export.prepare_export(body, row, review=review)
    else:
        request, _ = export.prepare_export(body, row, review=review)
        (root/'environment.json').write_text('{"changed":true}')
        monkeypatch.setattr(export.pipeline, 'export_experiment', lambda *a, **k: pytest.fail('changed source exported'))
        with pytest.raises(ValueError, match='review|snapshot|changed'):
            export.run_export(request, tmp_path/'refused')
