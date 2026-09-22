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
