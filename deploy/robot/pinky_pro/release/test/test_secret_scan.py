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
