import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import secret_scan  # noqa: E402

# Assemble the planted key at runtime so no private-key literal reaches the
# tracked source, and use a KNOWN_FIXTURES passphrase for the Wi-Fi line.
_BEGIN = "-----BEGIN " + "PRIVATE KEY-----"
_END = "-----END " + "PRIVATE KEY-----"


def test_scan_text():
    bad_text = "\n".join([
        _BEGIN,
        "MIIEvQIBADANBgkqhkiG9w0B" + "AQEFAASCBKcwggSjAgEAAoIBAQDE",
        _END,
        "",
        'psk="' + "Sk8rBoi9" + 'Delta"',
    ])
    findings = secret_scan.scan_text("test.py", bad_text)
    kinds = [f.kind for f in findings]
    assert "private-key" in kinds
    assert "wifi-psk" in kinds


def test_psk_field_can_forward_a_form_value_without_a_literal_finding():
    assert secret_scan.scan_text(
        "operations.js", 'postHost(connect, {ssid: name, psk: passwordField.value}, "confirm");',
    ) == []


def test_a_journal_quote_of_a_removed_fixture_is_excused_on_its_one_path(tmp_path):
    """D-347 회차(2026-09-29): 저널은 append-only라 문구를 못 고친다 —
    경로에 핀으로 고정된 인용만 면제다."""
    pinned = tmp_path / "operations/fleet/logs.md"
    pinned.parent.mkdir(parents=True)
    # Assemble at runtime: this test file lives under a test tree, but the
    # scanner must never see the literal as a plain string either.
    quote = 'api_key="' + "fixture-" + 'secret"'
    pinned.write_text(f"- 변경: 옛 리터럴 `{quote}` 를 허용 키로 바꿨다.\n", encoding="utf-8")

    findings = secret_scan.scan_files([pinned], root=tmp_path)
    assert findings == []


def test_the_same_quote_anywhere_else_is_still_a_secret(tmp_path):
    """산탄 증명: 한 경로의 면제는 같은 값의 다른 위치를 풀어주지 않는다."""
    code = tmp_path / "operations/fleet/fleet/server/app.py"
    code.parent.mkdir(parents=True)
    literal = 'api_key="' + "fixture-" + 'secret"'
    code.write_text(f"client = Client({literal})\n", encoding="utf-8")

    findings = secret_scan.scan_files([code], root=tmp_path)
    assert [f.kind for f in findings] == ["credential"], (
        "the prose excuse must stay pinned to the one journal path"
    )

def test_nullable_kotlin_annotations_keep_credential_defaults_visible():
    slot = 'request' + 'Secret'
    argument = 'sec' + 'ret'
    bearer_name = 'bear' + 'er'
    declaration = 'private var ' + slot + ': String? = '
    assert secret_scan.scan_text('Client.kt', declaration + 'null') == []
    signature = 'fun call(' + argument + ': String? = null, ' + bearer_name + ': String? = null): String {'
    assert secret_scan.scan_text('Client.kt', signature) == []
    leaked = declaration + '"' + 'live' + '9182aeb27c4d"'
    assert any(f.kind == 'credential' for f in secret_scan.scan_text('Client.kt', leaked))
    assert secret_scan.scan_text('config.yaml', argument + ': String? = null')


def test_generated_request_secrets_and_named_slot_reads_are_code():
    assert secret_scan.scan_text('service.py', 'secret = secrets.token_urlsafe(32)') == []
    assert secret_scan.scan_text('service.py', 'def _row(self, request_id, secret=None):') == []
    assert secret_scan.scan_text('Client.kt', 'requestSecret = string(created, "request_secret", 43)') == []
    slot = 'request' + 'Secret'
    leaked = slot + ' = string(created, "' + 'live' + '9182aeb27c4d", 43)'
    assert any(f.kind == 'credential' for f in secret_scan.scan_text('Client.kt', leaked))
    leaked_call = 'sec' + 'ret = secrets.token_urlsafe("' + 'live' + '9182aeb27c4d")'
    assert any(f.kind == 'credential' for f in secret_scan.scan_text('service.py', leaked_call))
    for filename in ('config.py', 'config.yaml'):
        quoted_call = 'pass' + 'word = "secrets.token_urlsafe(32)"'
        assert any(f.kind == 'credential' for f in secret_scan.scan_text(filename, quoted_call))
    ambiguous_slot = slot + ' = decrypt("request___secret")'
    assert any(f.kind == 'credential' for f in secret_scan.scan_text('Client.kt', ambiguous_slot))


def test_public_peer_vectors_are_bound_to_exact_path_field_and_value():
    for field, values in secret_scan._PEER_PUBLIC_VECTOR_VALUES.items():
        for value in values:
            line = '  "' + field + '": "' + value + '",'
            assert secret_scan.scan_text(secret_scan._PEER_VECTOR_PATH, line) == []
            assert secret_scan.scan_text('other.json', line)
            assert secret_scan.scan_text(secret_scan._PEER_VECTOR_PATH, line.replace(field, 'api_token'))
            changed = line.replace(value, value[:-1] + ('3' if value[-1] != '3' else '4'))
            assert secret_scan.scan_text(secret_scan._PEER_VECTOR_PATH, changed)
            mixed = line + ' api_' + 'token="' + 'live' + '9182aeb27c4d"'
            assert any(f.kind == 'credential' for f in secret_scan.scan_text(secret_scan._PEER_VECTOR_PATH, mixed))


def test_camera_public_vectors_keep_other_fields_and_paths_protected():
    path = 'operations/ui/cam/app/src/test/resources/camera-peer-transcripts.json'
    nonce = '01' * 32
    signature = ('MEQCIB8WKmontsmONrEJCGMhZ+'
                 'ioZLoH4cDiBfq6s6FlP99GAiB'
                 'tnNpxoX+FyYb20FDkoCxWsDWlZ'
                 '50nT7yzs6l+5v+VAw==')
    for field, value in [('nonce', nonce), ('signature', signature)]:
        line = '  "' + field + '": "' + value + '",'
        assert secret_scan.scan_text(path, line) == []
        assert secret_scan.scan_text('other.json', line)
        assert secret_scan.scan_text(path, line.replace(field, 'api_token'))
        assert secret_scan.scan_text(path, line.replace(value, '03' * 32))
        leaked = line + '\napi_' + 'token="' + 'live' + '9182aeb27c4d"'
        assert any(f.kind == 'credential' for f in secret_scan.scan_text(path, leaked))
    key_header = '-----BEGIN ' + 'PRIVATE KEY-----'
    assert any(f.kind == 'private-key' for f in secret_scan.scan_text(path, key_header))
