# 통합 관제 정보·정지 요청 소프트웨어 검증

각 관제는 직접 소유한 자원·원장과 장치 연결을 유지한다. 통합관제는 동일한 Fleet 구성으로 독립 운영하며 직계 자식의 제한된 정보를 모으고 선택한 subtree에 정지 요청을 전달한다. 부모 등록은 구동 권한을 만들지 않는다. 실제 배치와 방향별 인증·CA 구성은 [관제 역할·네트워크](../../deployment/control-units.md), 계약은 [D-862](../../adr/D-862-integrated-control-information-and-stop-requests.md)를 따른다.

## 커밋에 결속한 원격 실행

공식 `tools/remote/remote_pytest.py --sha <commit> --log-dir <외부 경로> -- <targets>`로 실행하고 각 run-1.txt를 `test/known_failures.py`와 비교했다. 아래 집중 실행은 모두 SKIP0·NEW0이다. 로그는 개발 PC 임시 보관이며 이 문서와 HTTP receipt가 제품 근거다.

| commit | 실제 실행 범위 | PASS |
|---|---|---:|
| `aaaf7ed3f22c32b7068aa5d66819c3b12e52c2fc` | 정보 생산자·중첩 수집/HTTP·소유권/자격·SQLite 정지 원장·취소/종료 경합·실제 TCP/TLS 집중 그룹 | 179 |
| `10fc37221203a4e5622938272dadb2b00580557d` | CORE HTTP 정지·응답 유실·재무장 guard 연계 | 21 |
| `ef83569895ba9c4e79bd25215af9aba237644a88` | 합성 R/A/A1/B sample API·관제별 stale fence·독립 처리 | 39 |
| `bbffbf8577ce1968ad293ac4f8e4d5d7113ea83c` | opt-in Chromium 통합 UI·실제 sample/기존 sample와 기존 Node 단위 그룹 | 33 |
| `ef6dc95958fcb2dab5c3090d9f68d65c1f7767f7` | 실제 ASGI 정보/지도·정지 전달/GET-only 재시작·기명 로컬 처분 HTTP capture | 5 |
| `ef6dc95958fcb2dab5c3090d9f68d65c1f7767f7` | 배치 overlay 계약·async keyword streaming 증거 수집기 | 2 |
| `45d1f72ac0` | 실제 Fleet HTTP·SharedGather·SQLite·지도·인증·정지 원장에 연결한 Chromium, API 가로채기 없음 | 1 |

집중 target은 `operations/fleet/test/test_integrated_control_http_pipeline.py`, 새 `test_control_unit_*`/`test_control_stop_*` 회귀, `test/test_control_unit_wire_transport.py` 계열과 CORE `test_integrated_control_core_stop.py`를 포함한다. browser 실행은 `ROSY_RUN_BROWSER_TESTS=1`로 `operations/fleet/test/test_integrated_control_browser.py`, `applications/fleet/test/test_integrated_sample_browser.py`, `applications/fleet/test/test_sample_browser.py`, `operations/fleet/test/test_site_map_api.py::test_console_web_node_unit_tests_pass`와 `test/test_integrated_control_backend_browser.py`를 실행했다. HTTP capture는 `ROSY_CAPTURE_FLEET_APP_CONTRACTS=1`로 nested producer, lost-reply restart, local attestation 세 함수를 실행했다. 실제 통과 node/응답 status/commit은 `applications/fleet/test/backend_http_evidence.json`에 보존한다.

## 실패와 수정의 구분

- 새 기능 전 credential RED8건으로 전용 관제 자격의 일반 Task/Cell API 접근을 재현하고 공통 인증 경계에서 제한했다. 기능 RED는 새 모듈이 없어 collection3건이 실패했다.
- CORE 첫 집중 실패는 시험 AsyncClient의 base_url 누락이었다. fixture를 고치고 기존 정지·UNKNOWN assertion을 유지했다.
- sample RED8건으로 전체409·소비 전 fence·HOLD 집계 누락을 재현했다. stale 관제는 실행하지 않고 최신 독립 관제는 계속 처리한다.
- 실제 browser가 viewer 조회 잠금과 정지 후 과거 overview 세대를 찾았다. 읽기 버튼만 기존 read 권한으로 표시하고, fresh overview와 같은 authority epoch인 최신 stop receipt만 fence에 반영했다.
- capture5건의 첫 실패는 관찰 wrapper가 request keyword를 받지 못한 시험 수집기 문제였다. 원래 send signature를 보존하고 별도 keyword-stream 회귀를 추가했다. 실패 실행의 응답을 성공 receipt로 등록하지 않았다.

## 검토와 수용 한계

독립 계약 검토는 backend 구현과 후속 UI/배치/관찰기/실제 backend browser 소스에서 지원되는 Critical/Important finding이 없음을 확인했다. reviewer는 시험 실행자를 대신하지 않는다. 원장 latch·CORE/OMX owner·개인정보 제외·UNKNOWN guard·GET-only 조회·같은 epoch fence를 검토했다.

선행 공유 계약은 `7a3d0dc8926760593b8a6dad4ba2cc26224a04fa`로 로컬 main에 착지했다. 해당 FULL27 호출에서 G1 timing의 원래 suite/자동 재실행 실패와 공식 격리 통과(LOAD-FLAKY)를 구분한다. 이번 runtime의 최종 착지 결과는 후속 기록에서 확인한다.

중첩 ASGI는 실제 producer/collector/route/SQLite를 연결하지만 합성 장치 transport를 사용한다. TCP/TLS는 시험 인증서와 loopback peer를 사용한다. 실제 backend browser는 독립 R 구성이고 다중 PC 증거가 아니다. sample 계층은 프로세스 내부 합성이다. CORE HTTP 통과도 실물 구동·정지 증거가 아니다. 모든 정지 결과의 physical_stop은 UNVERIFIED를 유지한다.

실제 PC별 설치·인증서/방화벽·양방향 LAN·장치 및 현장 복구는 목표 N1–N3으로 남는다. push·배포·장치 이동은 실행하지 않았다.

CE: 해당 없음 — 수정 원인과 재발 방지 조건이 D-862·제품 회귀·관찰기 signature에 직접 남아 별도 교훈 문서를 늘리지 않는다.
