"""D-359 US-009 — host runtime gaps are named in Korean; the raw keys stay in title."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

SYSTEM = Path(__file__).resolve().parents[1] / "panels" / "host" / "system.js"
ALL_KEYS = ["os_release", "hostname", "uptime", "load", "cpu", "memory", "temperature",
            "storage", "network_counters"]


def _gap(unavailable):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = (f'import {{ runtimeGap }} from {json.dumps(SYSTEM.as_uri())};\n'
              f"console.log(JSON.stringify(runtimeGap({json.dumps(unavailable)})));\n")
    result = subprocess.run([node, "--input-type=module", "--eval", script], check=True,
                            capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def test_nothing_missing_needs_no_gap_line():
    assert _gap([]) is None
    assert _gap(None) is None


def test_missing_sources_read_as_korean_labels_with_keys_in_title():
    assert _gap(["os_release", "load", "network_counters"]) == {
        "text": "호스트 런타임 일부 확인 불가: 운영체제, 부하, 네트워크 통계",
        "title": "os_release, load, network_counters"}
    assert _gap(["hostname", "uptime", "cpu", "memory", "temperature"])["text"] == (
        "호스트 런타임 일부 확인 불가: 호스트 이름, 가동 시간, CPU, 메모리, 온도")


def test_an_unknown_key_is_shown_as_received():
    assert _gap(["gpu"])["text"] == "호스트 런타임 일부 확인 불가: gpu"


def test_every_source_missing_is_one_plain_sentence():
    for keys in (ALL_KEYS, ALL_KEYS + ["ros_graph"]):
        gap = _gap(keys)
        assert gap["text"] == "호스트 런타임 정보를 받지 못했습니다"
        assert gap["title"] == ", ".join(keys)


def test_the_label_map_covers_every_key_core_can_name():
    source = (SYSTEM.parents[4] / "runtime" / "gateway" / "core" / "system" / "runtime.py").read_text(encoding="utf-8")
    import re
    named = set(re.findall(r'unavailable\.append\("([a-z_]+)"\)', source))
    assert named == set(ALL_KEYS) | {"ros_graph"}
    for key in named:
        assert _gap([key])["text"] != f"호스트 런타임 일부 확인 불가: {key}", key
