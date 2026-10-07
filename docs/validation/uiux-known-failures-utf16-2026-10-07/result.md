# UI/UX pytest 실패 비교 인코딩 보정 — LOCAL

기준은 로컬 `main` `432445eed`다. Windows PowerShell의 `*>`로 저장한 pytest 출력은 UTF-16LE BOM(`FF FE`)인데, `test/known_failures.py`가 UTF-8로만 읽어 실패 줄을 찾지 못했다. 따라서 이런 로그에 대한 과거 `0 NEW` 표시는 실패가 없다는 근거가 아니다. pytest 자체의 종료 코드와 통과 수는 별도로 유효하다.

UTF-16 회귀 시험을 먼저 추가해 **1 failed, 5 passed**를 재현했다(`X:/DevTemp/known-failures-utf16/red.txt`). BOM에 따라 UTF-16 또는 UTF-8로 읽도록 수정한 뒤 **6 passed**였다(`green.txt`). 수정된 비교기는 과거 Pilot 전체 실패 로그 `X:/DevTemp/uiux-pilot-current/run.txt`에서 320×568 카메라 면적 실패 **1 NEW**, `X:/DevTemp/pilot-camera-320/postmerge-full.txt`에서 응급 카메라 타임아웃 **2 NEW**를 보고했고 각각 종료 코드 1이었다. 통과 로그 `green.txt`는 **0 NEW**, 종료 코드 0이었다.

이는 실패 분류 도구의 LOCAL 보정이다. [기존 Pilot 카메라 기록](../uiux-pilot-camera-area-2026-10-07/result.md)의 전체 실행 **115 passed, 1 failed**와 **114 passed, 2 failed**는 여전히 실패 실행이며, 이 실행에 인용된 옛 `known_failures.py 0 NEW`는 취소한다. 제품 전체 G2, 실물 readback, 사용자 G3 판정은 **HOLD**다.
