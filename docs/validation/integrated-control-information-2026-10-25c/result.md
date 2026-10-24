# 통합관제 정보·정지 요청 최종 소프트웨어 착지

구현은 commit `9b10086126`으로 로컬 main에 반영했다. 공식 `tools/land.py --tests auto --no-prune`가 exit0으로 종료했고 main ancestry를 확인했다. push·실제 배포·로봇 이동은 하지 않았다.

각 관제는 자기 자원·원장·운영자 승인과 CORE/OMX 연결을 소유한다. 통합관제는 같은 Fleet 구성으로 독립 운영하거나 하위 관제를 포함하며, 상위에는 서브 관제로 참여한다. 직계 정보 수집과 정지 요청은 방향별 자격·명시 공유/수신 허용·검증된 TLS를 사용한다. [역할·네트워크·기동 구성](../../deployment/control-units.md)과 [목표 I1–I6](../../plans/2026-10-23-composable-control-goals.md)을 함께 본다.

## 공식 실행과 source 결속

모든 pytest는 커밋된 source를 공식 원격 runner로 실행했다. 로그는 개발 PC `%TEMP%` 아래 `rosy-integrated-runtime-second-full`의 `feat-integrated-control-runtime`에 있다. 착지 transcript는 같은 임시 루트 아래 `rosy-integrated-runtime-land-merged`의 `runner-transcript.txt`다. 아래 source와 실행 범위를 섞지 않는다.

| source | 실행 범위 | 결과 |
|---|---|---|
| `e7cdace7f6` | Chromium 포함 FULL27 invocation | 모든 원본 known-failure 비교 NEW0·KNOWN0·FLAKY0 |
| `e7cdace7f6` | root / Fleet / CORE·공유 그룹 | 각각10038/6391/7444 PASS, SKIP1139/362/91 |
| `e7cdace7f6` | opt-in Chromium4그룹 | 각각118/181/121/143 PASS, SKIP0 |
| `9b10086126` | 최신 main 병합 후 구조 guard | 273 PASS·NEW0 |
| `9b10086126` | 기본 FULL23 invocation | NEW0; 기존 quarantine timing2건은 같은 SHA 재실행 통과 |
| `9b10086126` | Fleet / CORE·공유 그룹 | 6391/7444 PASS, SKIP362/91 |
| `9b10086126` | root 원래 실행 | 2 FAIL, 10036 PASS, 1139 SKIP |
| `9b10086126` | root 기존 quarantine 재실행 | 2 PASS, 5.50초; 원래 실패를 FLAKY로 구분 |

선행 FULL을 마친 뒤 공식 대기열에서 최신 main을 병합했다. main의 known-failure 목록 변경 때문에 공식 선택기가 기본 FULL을 다시 요구했다. 최신 source의23개 기본 로그와 별도 재실행 로그1개를 각각 known_failures와 비교했고 모두 exit0이다. 이 실행은 시간 검사2건의 원인 해결이나 무조건적인 첫 실행 통과를 뜻하지 않는다. threshold·quarantine·known-failure 목록을 이번 작업에서 바꾸지 않았다.

기존 시간 검사는 `test/test_platform_g1_timing.py`의 coordinated pairs와 coordinator kill 사례다. 동일 source의 실제 재실행을 원본에 결속했으며 교차 SHA 결과를 사용하지 않았다. 원인 확정·quarantine 재검토는 소유 검사의 별도 작업이다. 최신 main이 가져온 theme browser 목록 항목의 not-failing-here 표시도 해당 문제 해결 증거로 해석하지 않는다.

최신 main 병합 전후 Fleet runtime·Console·shared/web 파일 차이가 없음을 확인했다. 따라서 공식 선택기의23개 기본 재검증과 별도로, 통합 예제 및 API 가로채기 없는 실제 Fleet backend Chromium을 포함한 선행4개 browser 그룹의 source 근거를 유지한다. browser143그룹에는 `test/test_integrated_control_backend_browser.py`가 포함된다.

## 수용한 기능과 한계

- 실제 SharedGather·직접 소유 SQL·활성 지도에서 제한된 정보를 만들고 R/A/A1/B 중첩 HTTP 수집으로 연결·신선도·소유 관제·지도 출처를 유지한다. 개인 actor/request/evidence는 정보 projection에 포함하지 않는다.
- immutable stop identity/fence와 원자적 journal·latch, 중복·응답 유실·재시작·부분 실패, 활성 전송/미확인 재무장 guard를 검증했다. 복구 기록은 기명 로컬 확인이며 자동 재무장이나 물리 정지 증거가 아니다.
- 직계 전용 service 자격의 일반 API 접근을 차단하고 명시 CA·deadline·byte cap·opt-in Fleet-only 읽기 전용 mount를 연결했다. 설정 계약과 시험 인증서의 실제 loopback TCP/TLS를 검증했다.
- backend와 후속 UI/배치/증거 수집기·정확한 공개 safety anchor는 독립 검토를 받았다. 현재 source의 안전·크기·lint 게이트도 통과했다.

[집중 증거](../integrated-control-information-2026-10-25/result.md)와 [첫 FULL 실패·교차 SHA 오분류 무효화](../integrated-control-information-2026-10-25b/result.md)는 보존한다. 테스트 장치 transport와 sample은 합성이며, 모든 physical_stop은 UNVERIFIED다. 실제 PC 설치·양방향 LAN/TLS·장치·현장 복구 수용 N1–N3은 남는다.

CE: 해당 없음 — source 결속·경계 등록·재발 방지가 코드·회귀와 이 검증 기록에 직접 남는다. 기존 시간 민감 검사의 원인 해결을 주장하지 않는다.
