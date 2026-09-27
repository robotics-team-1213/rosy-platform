# Fleet G2/G3 상태 평가 — 2026-09-27

**판정: HOLD (LOCAL).** D-153의 Fleet 표면 질문은 "어느 로봇과 대형에 개입해야 하는가"이다. 선언 뷰포트는 사이트 PC 1920×1080, 보조 전화 390×844 및 320×844이다. 후자의 절차는 세로 스크롤이다. 이 문서의 응답은 모두 Playwright fixture이며 실제 Fleet 서버·로봇 상태가 아니다.

## 재생 방법과 범위

- 소스: `test/test_fleet_console_browser.py`의 상태 fixture와 `X:\DevTemp\rosy-uiux-d306\capture_fleet_g2.py`.
- 명령: `python -X utf8 X:\DevTemp\rosy-uiux-d306\capture_fleet_g2.py`. 27개 PNG와 `capture.json`은 `X:\DevTemp\rosy-uiux-d306-fleet-g2\`에 둔다. X: 파일은 일회성 로컬 증거이며 저장소 아카이브가 아니다.
- 회귀: `$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest test/test_fleet_console_browser.py test/test_web_dialog_contract.py -q -p no:cacheprovider`.
- 8개 상태 × 3개 뷰포트 모두 페이지 오류 0, 가로 넘침 0. 1920×1080은 세로 넘침 0, 390/320px은 세로 스크롤이 있다. `capture.json`의 `goalDisabled` 및 `estopDisabled`는 해당 순간 DOM 속성이다. 최초 기동 순간 3개 캡처를 별도로 찍었다.

| 상태 | fixture / 실제 읽기 | 캡처 이름 (`{폭}x{높이}`) | 결과 |
|---|---|---|---|
| fresh | 3/3 연결, 각 로봇의 pose·battery·safety, 대형 RUNNING | `fresh_{폭}x{높이}.png` | LOCAL 확인 |
| delayed | 팔로워 1.2 Hz 지연, 다른 팔로워 끊김 | `delayed_{폭}x{높이}.png` | 지연 구분 확인. **팔로워 지연의 나이가 응답에 없어 G3 위반** |
| disconnected | 2/3 연결, `rosy_03` OFFLINE 및 CONNECT_ERROR | `disconnected_{폭}x{높이}.png` | 결측과 이유 확인; 오프라인 목표 비활성 |
| unavailable | `rosy_01` 안전 상태 `null` | `unavailable_{폭}x{높이}.png` | SAFETY `정보 없음`, 목표 비활성, 사유 표시. 다른 로봇 목표는 활성 |
| 빈 목록·미등록 | 0/0 연결 | `empty_{폭}x{높이}.png` | `등록된 로봇이 없습니다`와 페어링 안내 |
| 최초 기동 | 인증 응답 대기, 데이터 미수신 | `first_boot_{폭}x{높이}.png` | `로봇 목록 불러오는 중`; 느린 서버 회복 전이는 미검증 |
| 오류 | state gather HTTP 500 | `error_{폭}x{높이}.png` | `Fleet 서버 없음`, 로봇 영역의 연결 확인 안내 |
| SAFE_STOP 표시 | `rosy_01`의 `safety.estop=true` fixture | `estop_{폭}x{높이}.png` | E-STOP 및 목표 비활성. 물리 정지의 readback은 아님 |
| 권한 거부 | session role `viewer` | `viewer_{폭}x{높이}.png` | 모든 목표와 전체 정지 비활성 |

불가역 조작은 `test_fleet_estop_requires_confirm_and_decline_blocks_it`에서 전체 정지 확인 취소 시 POST 0, 수락 시 POST 1과 `물리 정지 미확인` 응답 문구를 검증한다. 목표 전송도 별도 확인을 지나며 취소 시 POST 0, 수락 시 1이다. 브라우저 기본 `window.confirm` 대화상자의 픽셀 캡처는 현재 회차에 없으므로 그 **G2 셀은 미평가**다. 최초 기동은 인증 응답을 무기한 대기시킨 순간을 캡처했고, 느린 서버 회복 전이는 미검증이다.

## G3 여덟 항목

| 항목 | 판정과 근거 |
|---|---|
| 정직 | 안전 정보가 없으면 `정보 없음`으로 표시하고 목표 지정은 비활성. 선택 후 안전 정보가 사라져도 선택 해제 및 전송 차단 (`test_armed_goal_is_withdrawn_when_safety_becomes_unknown`). |
| 증거 상태 | fresh/delayed/disconnected/unavailable을 분리했지만 팔로워 지연 나이가 없다. **위반**, Fleet 응답 계약에 시각·age 필드 필요. |
| 색 | `unavailable_1920x1080.png`와 `estop_390x844.png` 검토. 정상 로봇에도 식별용 색 경계가 있고 지도 점유/로봇은 의미색을 쓴다. concept 16 §7.3의 "문제 로봇만 색 행" 원칙과의 관계가 **미해결**이다. |
| 위계 | 지도와 로봇 개입 영역을 분리하고 전체 정지는 상단 고정. 1920px 단일 화면 및 모바일 세로 절차 확인. |
| 불가역 | 전체 정지·목표 전송은 confirm 취소/수락 회귀를 통과. 기본 대화상자 시각 캡처는 미평가. |
| 어휘 | 오프라인·정보 없음·취소 및 물리 정지 미확인을 한국어로 명시. fixture의 코드값 `CONNECT_ERROR`는 원인 식별 정보로 병기. |
| 표면 질문 | 개입 대상과 차단 이유는 표시한다. 확인 대화상자 픽셀 캡처와 느린 서버 회복 전이가 빠져 전 상태 판정은 HOLD. |
| 문법 | 1920px에서는 페이지 세로 스크롤 0, 모바일 가로 넘침 0. 정상 로봇도 로스터 기본 화면에 모두 보이므로 concept 16 §7.3의 "주의 필요한 로봇이 기본" 원칙에 **위반**한다. 필터·전체 목록 탐색·키보드 접근을 함께 설계해야 한다. |

LOCAL 캡처는 장치 단일 publisher, 실제 E-STOP, 로봇 움직임, 현장 거리에서의 판독성을 증명하지 않는다. 이 회차에서 Fleet UI/UX GO를 선언하지 않는다.

## 2026-09-27 D-309 Fleet 송신 증거 보완

- 이전 27개 PNG는 변경 전 화면의 로컬 기록이다. 현재 화면의 새 캡처로 대체하지 않았으므로 시각 G2/G3 전체를 통과 처리하지 않는다.
- 서버 릴레이의 `follower_last_tx_age_s`와 `stream_evidence`가 추가됐다. 서버가 경과 시간 1초를 판정하고 화면은 `delayed`의 나이, `disconnected`, `unavailable`을 표시한다. 송신은 팔로워 수신·물리 추종 증거가 아니다.
- 검증: Fleet 서버 focused 44 passed, Fleet Playwright 21 passed (Windows LOCAL). 이전 표의 팔로워 시간 필드 위반은 코드와 테스트 범위에서 해결됐다. 예외 우선 목록과 현재 캡처, DEVICE/FIELD는 HOLD다.
