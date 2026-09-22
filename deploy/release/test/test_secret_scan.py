import pytest
from deploy.release import secret_scan

def test_scan_text():
    # Should flag Private keys and WPA keys
    bad_text = '''
    -----BEGIN PRIVATE KEY-----
    MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDE
    -----END PRIVATE KEY-----
    
    psk="supersecretwifi"
    '''
    findings = secret_scan.scan_text("test.py", bad_text)
    kinds = [f.kind for f in findings]
    assert "private-key" in kinds
    assert "wifi-psk" in kinds
