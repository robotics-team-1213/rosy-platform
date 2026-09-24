"""장비 목록: Pinky에 붙은 것과 현장의 신호·ESP는 한 문서에서 다른 칸이다."""

import pytest

from core_common.equipment import parse_catalog
from core_common.intent import IntentError

PINKY = """
robots:
  rosy_01:
    - {id: drive, kind: drive, bus: uart, path: /dev/ttyAMA4}
    - {id: adc, kind: range, bus: i2c, path: /dev/i2c-1}
    - {id: lamp, kind: lamp, bus: gpio, path: gpio19}
site:
  - {id: signal_1, kind: signal, bus: http, path: http://127.0.0.1:8095}
  - {id: esp_signal_1, kind: esp, bus: http, path: http://127.0.0.1:8088, attached_to: signal_1}
"""


def test_pinky_and_the_signal_share_a_document_and_not_a_list():
    catalog = parse_catalog(PINKY)
    assert [item.id for item in catalog.robots["rosy_01"]] == ["drive", "adc", "lamp"]
    assert [item.kind for item in catalog.site] == ["signal", "esp"]
    assert catalog.site[1].attached_to == "signal_1"


def test_a_signal_is_not_a_pinky_attachment():
    text = """
robots:
  rosy_01:
    - {id: signal_1, kind: signal, bus: http, path: http://127.0.0.1:8095}
site: []
"""
    with pytest.raises(IntentError) as caught:
        parse_catalog(text)
    assert caught.value.code == "WRONG_PLACE"


def test_esp_must_name_a_real_site_device():
    text = """
robots: {}
site:
  - {id: esp_1, kind: esp, bus: http, path: http://127.0.0.1:8088, attached_to: missing}
"""
    with pytest.raises(IntentError) as caught:
        parse_catalog(text)
    assert caught.value.code == "UNKNOWN_EQUIPMENT"
