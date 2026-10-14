# Fleet 앱 바와 레일 이름 — 증거 상태

대상: [D-741](../adr/D-741-unified-app-shell-seats.md) 조각 4·5, 브랜치 `feat/fleet-app-bar`. 이 문서는 D-153의 세 관문이 지금 어디까지 있는지 적는다. 있는 것만 있다고 적는다.

| 관문 | 상태 | 근거 |
|---|---|---|
| G1 값과 문법 (기계) | 소스 시험 통과 | 원격 pytest 로그 `X:\DevTemp\fleet-app-bar\t5-fleet-run-1.txt`, `t5-web-run-1.txt`(커밋 `9e2d4ef0c`). `known_failures` NEW 0. node 단위 시험은 `test_site_map_api.py::test_console_web_node_unit_tests_pass`가 원격에서 돌렸다 |
| G1 브라우저 측정 | 없음 | `operations/fleet/test/*_browser.py`는 푸시 뒤 CI에서만 돈다. 실행 번호를 받으면 이 칸에 적는다 |
| G1 브라우저 측정(CI 밖) | 없음 | `test/test_fleet_console_browser.py`, `shared/web/test/test_theme_browser.py`는 CI도 켜지 않는다. Chromium이 있는 PC에서 사람이 돌려야 한다 |
| G2 상태 매트릭스 (캡처) | 없음 | 네 문서 × 320·390·768·1024·1366·1920 × 어둡게·밝게. `ROSY_SHOT_DIR`을 주고 `test_fleet_header_browser.py`를 돌리면 문서·폭마다 한 장이 나온다(어둡게만) |
| G3 법 체크리스트 (사람) | 없음 | 계획 문서 Task 7의 목록 |

설치본, 현장 PC, 실물 화면 수용은 없다.
