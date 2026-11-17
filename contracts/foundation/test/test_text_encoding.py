from core_common.text_encoding import double_encoded_paths, looks_double_encoded


def _mangle(text: str) -> str:
    return "".join(chr(b) if b in (0x81, 0x8D, 0x8F, 0x90, 0x9D) else bytes([b]).decode("cp1252")
                   for b in text.encode("utf-8"))


def test_detects_double_encoded_korean():
    for word in ("상단", "가로 세로", "하역장 3번"):
        assert looks_double_encoded(_mangle(word))
    assert looks_double_encoded(_mangle("상단").replace("", ""))


def test_valid_text_passes():
    for word in ("상단", "Café", "München 2", "dock-1", "", "A→B", "naïve", "日本語", "1.2×·1.4"):
        assert not looks_double_encoded(word)


def test_paths_name_the_field():
    body = {"places": [{"id": "a", "name": "상단"}, {"id": "b", "name": _mangle("하단")}]}
    assert list(double_encoded_paths(body)) == ["places.1.name"]
