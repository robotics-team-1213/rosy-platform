"""ROOT original-file composition; explicit ports only, no default activation."""
import hashlib
import json
from pathlib import Path
import re


def load_frozen_json(source, *, expected_sha256):
    if type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
        raise ValueError('EXTERNAL_OPERATING_FILE_PIN_REQUIRED')
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs): raise ValueError('DUPLICATE_OPERATING_ORIGINAL_FIELD')
        return result
    def nonfinite(value):
        raise ValueError('NONFINITE_OPERATING_ORIGINAL')
    try:
        with Path(source).open('rb') as stream: raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError('OPERATING_ORIGINAL_BYTES_DIFFER')
        document = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique, parse_constant=nonfinite)
        if type(document) is not dict: raise ValueError('OPERATING_ORIGINAL_OBJECT_REQUIRED')
        return document
    except (OSError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError('OPERATING_ORIGINAL_READ_FAILED') from error


def import_operation(owner, grant_id, receipt, *, evidence):
    if not callable(evidence) or not callable(getattr(owner, 'apply', None)):
        raise ValueError('EXPLICIT_EXISTING_OPERATION_OWNER_REQUIRED')
    proof = evidence(grant_id)
    report = proof.get('report') if type(proof) is dict else None
    if (type(report) is not dict or report.get('state') != 'PASS_FOR_OPERATION'
            or report.get('field_accepted') is not True or report.get('truth_admitted') is not True
            or report.get('missing') != []):
        raise ValueError('ORIGINAL_OPERATING_EVIDENCE_HOLD')
    return owner.apply(grant_id, receipt)
