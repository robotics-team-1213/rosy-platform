"""D-136 T1: CORE는 영상 바이트를 만지지 않는다.

`core` 5패키지의 생산 코드가 영상 라이브러리를 import하거나 영상 API 토큰을
이름대면 실패한다. 테스트 픽스처의 합성 영상(cv2)은 제외 — 도구지 런타임이
아니다. 소스 텍스트 단언이 동어반복이 되지 않게, 위반을 직접 넣어 적색을
확인했다 (mutation-proven).
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
PACKAGES = ("core", "core_common", "core_events", "core_features", "core_api_web")

FORBIDDEN_IMPORTS = frozenset({"cv2", "picamera2", "ffmpeg", "av", "PIL", "libcamera"})

# 런타임 영상 API의 이름들. 주석 언급이 아니라 실제 코드 토큰으로만 본다 —
# AST가 import를, 이 목록이 속성/문자열 사용을 잡는다.
FORBIDDEN_TOKENS = ("VideoCapture", "VideoWriter", "imencode", "imdecode",
                    "multipart/x-mixed", "image/jpeg", "RTSP", "WebRTC", "mjpeg")

# D-152: CORE may pass through one bounded latest JPEG without decoding or
# encoding it. No other production module receives a video/media API exception.
ALLOWED_VIDEO_TOKENS = {
    "core_api_web/core_api_web/api/v1/vision.py": frozenset({"image/jpeg"}),
}


def _prod_files():
    for package in PACKAGES:
        root = SRC / package
        for path in sorted(root.rglob("*.py")):
            if "test" in path.parts or path.name == "conftest.py":
                continue
            yield path


def _imported_top_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_core_production_imports_no_video_libraries():
    """D-136 T1: import 그래프에 영상 라이브러리 없음."""
    violations = {}
    for path in _prod_files():
        hit = _imported_top_names(path) & FORBIDDEN_IMPORTS
        if hit:
            violations[str(path.relative_to(SRC))] = sorted(hit)
    assert not violations, f"CORE production imports video libraries: {violations}"


def test_core_production_names_no_video_api():
    """D-136 T1: 영상 API 토큰 없음 (주석이 아니라 코드 토큰)."""
    violations = []
    for path in _prod_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(SRC).as_posix()
        allowed = ALLOWED_VIDEO_TOKENS.get(relative, frozenset())
        tokens = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                tokens.add(node.id)
            elif isinstance(node, ast.Attribute):
                tokens.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                tokens.add(node.value)
        hit = [token for token in FORBIDDEN_TOKENS if token not in allowed
               if any(token in found for found in tokens)]
        if hit:
            violations.append((relative, hit))
    assert not violations, f"CORE production names video APIs: {violations}"
