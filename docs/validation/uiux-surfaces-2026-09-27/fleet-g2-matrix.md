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
| delayed | 팔로워 1.2 Hz 지연, 다른 팔로워 끊김 | `delayed_{폭}x{높이}.png` | 최초 회차에는 응답 age 누락. D-309에서 서버 판정 age 표시를 보완하고 아래 현재 재촬영에서 `지연 · 2.1초`를 확인 |
| disconnected | 2/3 연결, `rosy_03` OFFLINE 및 CONNECT_ERROR | `disconnected_{폭}x{높이}.png` | 결측과 이유 확인; 오프라인 목표 비활성 |
| unavailable | `rosy_01` 안전 상태 `null` | `unavailable_{폭}x{높이}.png` | SAFETY `정보 없음`, 목표 비활성, 사유 표시. 다른 로봇 목표는 활성 |
| 빈 목록·미등록 | 0/0 연결 | `empty_{폭}x{높이}.png` | `등록된 로봇이 없습니다`와 페어링 안내 |
| 최초 기동 | 인증 응답 대기, 데이터 미수신 | `first_boot_{폭}x{높이}.png` | 당시 최초 조회 대기 상태. 느린 서버 회복은 아래 D-309 재촬영에서 별도 확인 |
| 오류 | state gather HTTP 500 | `error_{폭}x{높이}.png` | `Fleet 서버 없음`, 로봇 영역의 연결 확인 안내 |
| SAFE_STOP 표시 | `rosy_01`의 `safety.estop=true` fixture | `estop_{폭}x{높이}.png` | E-STOP 및 목표 비활성. 물리 정지의 readback은 아님 |
| 권한 거부 | session role `viewer` | `viewer_{폭}x{높이}.png` | 모든 목표와 전체 정지 비활성 |

불가역 조작은 `test_fleet_estop_requires_confirm_and_decline_blocks_it`에서 전체 정지 확인 취소 시 POST 0, 수락 시 POST 1과 `물리 정지 미확인` 응답 문구를 검증한다. 목표 전송도 별도 확인을 지나며 취소 시 POST 0, 수락 시 1이다. 이후 D-309 브라우저 dialog 기록에서 정확한 확인 문구와 취소/승인에 따른 POST 횟수를 확인했다. OS 기본 대화상자의 픽셀은 제품 G2 판정 대상이 아니다. 느린 서버 회복은 아래 D-309 재촬영에서 별도로 확인했다.

## 최초 G3 여덟 항목 판정 — D-309 이전 이력

다음 표는 초기 회차에서 발견한 위반과 미평가를 보존한다. 현재 판정으로 인용하지 않는다. D-309 수정 후 근거는 아래 **현재 G3 재평가**를 따른다.

| 항목 | 판정과 근거 |
|---|---|
| 정직 | 안전 정보가 없으면 `정보 없음`으로 표시하고 목표 지정은 비활성. 선택 후 안전 정보가 사라져도 선택 해제 및 전송 차단 (`test_armed_goal_is_withdrawn_when_safety_becomes_unknown`). |
| 증거 상태 | 당시 fresh/delayed/disconnected/unavailable 구분은 있었지만 팔로워 지연 나이가 없었다. **당시 위반; D-309에서 보완**. |
| 색 | 당시 정상 로봇에도 식별용 색 경계가 있어 concept 16 §7.3과의 관계가 **미해결**이었다. **D-309에서 정상 카드 장식색을 중립색으로 변경**. |
| 위계 | 지도와 로봇 개입 영역을 분리하고 전체 정지는 상단 고정. 1920px 단일 화면 및 모바일 세로 절차 확인. |
| 불가역 | 전체 정지·목표 전송은 confirm 취소/수락 회귀를 통과. 기본 대화상자 시각 캡처는 미평가. |
| 어휘 | 오프라인·정보 없음·취소 및 물리 정지 미확인을 한국어로 명시. fixture의 코드값 `CONNECT_ERROR`는 원인 식별 정보로 병기. |
| 표면 질문 | 최초 회차에서는 느린 서버 회복 전이가 빠져 있었다. **D-309 재촬영에서 로딩→응답 복귀를 확인**. |
| 문법 | 최초 회차에는 정상 로봇도 기본 목록에 모두 보여 concept 16 §7.3 원칙에 **위반**했다. **D-309에서 예외 우선 기본 목록과 전체 목록 disclosure를 구현**. |

LOCAL 캡처는 장치 단일 publisher, 실제 E-STOP, 로봇 움직임, 현장 거리에서의 판독성을 증명하지 않는다. 이 회차에서 Fleet UI/UX GO를 선언하지 않는다.

## 2026-09-27 D-309 Fleet 송신 증거 보완

- 이전 27개 PNG는 변경 전 화면의 로컬 기록이다. 현재 화면의 새 캡처로 대체하지 않았으므로 시각 G2/G3 전체를 통과 처리하지 않는다.
- 서버 릴레이의 `follower_last_tx_age_s`와 `stream_evidence`가 추가됐다. 서버가 경과 시간 1초를 판정하고 화면은 `delayed`의 나이, `disconnected`, `unavailable`을 표시한다. 송신은 팔로워 수신·물리 추종 증거가 아니다.
- 검증: Fleet 서버 focused 44 passed, Fleet Playwright 21 passed (Windows LOCAL). 이전 표의 팔로워 시간 필드 위반은 코드와 테스트 범위에서 해결됐다. 예외 우선 목록과 현재 캡처, DEVICE/FIELD는 HOLD다.

## 2026-09-27 D-309 Fleet 예외 우선 목록 보완

- 기본 로스터에는 연결 단절, 안전 상태 미확인·E-STOP, 개입 요청, 성능 저하, 주행 실패, 대기·양보, 릴레이 문제 로봇만 표시한다. 선택 중인 로봇은 계속 보인다.
- 정상 로봇은 `전체 로봇 보기`로 접근하며, 토글은 `aria-expanded`를 제공한다. 전체 지도의 로봇 표시는 유지한다. 정상 카드의 장식 색은 중립으로 바꿨다.
- Fleet Playwright 22 passed (Windows LOCAL). 기존 27개 PNG는 변경 전 캡처이며 신규 시각 수용으로 재사용하지 않는다. DEVICE/FIELD와 Fleet 전체 G2/G3는 HOLD다.

## 2026-09-27 D-309 변경 후 Fleet 재촬영

- 현재 코드에서 `X:\DevTemp\rosy-uiux-d309-fleet-g2\capture_fleet_g2.py`로 **8상태 × 3뷰포트 + 최초 기동 3뷰포트 = 27장**을 다시 찍었다. 24개 상태의 `capture.json`은 페이지 오류 0, 가로 넘침 0이다. 모바일 390×844·320×844는 아래 절차가 보이도록 전체 문서 길이를 캡처했다. X:는 일회성 LOCAL 근거다.
- 정상 3대 fixture는 개입 대상 `rosy_03` 한 대만 기본 목록에 보이고 `전체 로봇 보기 · 정상 2대`로 나머지를 찾는다. 빈 목록·첫 조회 중·오류에는 실제 토글이 숨겨진다. `delayed_390x844.png`의 `rosy_02`는 서버 판정 `지연 · 2.1초`가 목록에 보인다.
- 첫 상태 조회를 1.4초 보류한 `fleet_console_slow_loading.png`에서 중복 상태 GET 없이 대기 문구와 빈 경보 영역 숨김을 확인했고, `fleet_console_slow_recovered.png`에서 응답 후 개입 목록을 확인했다. 상태 상실 후 마지막 좌표를 숨기고 다시 읽는 별도 브라우저 회귀도 유지한다.
- 지도 격자는 픽셀 형태를 유지하면서 경로·오차 문구만 더 높은 캔버스 해상도로 그린다. `fresh_1920x1080.png`와 `delayed_390x844.png`에서 주석의 과대 확대·잘림을 시각 재검토했다. 목표 클릭의 좌표 변환과 키보드 확인 시험은 통과했다.
- `fleet_estop_preconfirm.png`, `fleet_goal_preconfirm.png`는 조작 버튼·대상을 보여 준다. 브라우저 dialog 기록은 정확한 확인 문구, 취소 시 POST 0, 승인 시 단일 POST와 서버 응답을 검증한다. D-309에 따라 OS 대화상자 픽셀은 제품 G2 판정 대상이 아니다.
- 변경 후 Fleet 브라우저 **24 passed**. 이는 LOCAL 경로 검증이다. 실제 사이트 서버·로봇 상태, E-STOP 물리 정지, 목표 이동 결과 및 G3 사람 평가가 없어 표면 전체와 DEVICE/FIELD는 **HOLD**다.

## 현재 G3 재평가 — D-309 변경 후 LOCAL 증거

아래는 위 과거 표의 정정된 현재 상태다. 판정은 저장된 fixture·Chromium 캡처에 대한 LOCAL 검토이며 사람 수용이나 실제 Fleet 수용을 뜻하지 않는다.

| 항목 | 최신 근거와 현재 판정 |
|---|---|
| 정직 | 안전 정보 없음·오프라인·E-STOP에서 해당 로봇 목표를 막고 이유를 표시한다. `unavailable` 및 E-STOP 캡처와 목표 비활성 회귀가 있다. **LOCAL 확인**; 물리 정지는 미확인. |
| 증거 상태 | `fresh`, `delayed`, `disconnected`, `unavailable`을 나누고 delayed는 서버 판정 나이를 표시한다. `delayed_390x844.png`에서 `지연 · 2.1초`를 확인했다. **초기 age 누락 수정, LOCAL 확인**. |
| 색 | 정상 카드 장식색은 중립색이며 이상 상태는 텍스트·상태 표시로 전달한다. 지도 점유·로봇 색은 지도 의미에 사용한다. **D-309 수정 후 LOCAL 재검토**; 색각 사용자·현장 조명 수용은 미평가. |
| 위계 | 지도와 개입 영역을 분리하고 전체 정지를 상단에 둔다. 예외 로봇을 기본 목록에 우선 표시하며 전체 로봇은 disclosure로 연다. **LOCAL 재촬영 확인**. |
| 불가역 | 정지·목표 확인에서 취소는 POST 0, 승인은 단일 POST와 서버 응답을 검증한다. OS 기본 dialog 픽셀은 제품 G2 판정 대상이 아니다. **브라우저 계약 확인**; 실제 정지·이동 결과는 미확인. |
| 어휘 | 지연 시간, 연결 끊김, 정보 없음, 요청 접수와 물리 정지 미확인을 한국어로 구분한다. `CONNECT_ERROR`는 원인 식별 정보로만 병기한다. **LOCAL 확인**. |
| 표면 질문 | 기본 목록에서 주의가 필요한 로봇과 차단 이유를 찾을 수 있고 정상 목록은 명시적으로 펼친다. 1.4초 지연 후 로딩 표시와 응답 복귀를 재촬영했다. **LOCAL 확인**; 실제 사이트 운용 판단은 미평가. |
| 문법 | PC 1920×1080에서 페이지 넘침 없이, 모바일 390/320px에서 가로 넘침 없이 세로 절차를 따른다. 목표 지도 키보드 이동·확인 시험도 통과했다. **선언한 fixture 뷰포트에서 LOCAL 확인**; 전 장치·현장 수용은 미평가. |

따라서 초기 G3 표의 age·색·기본 로스터 위반은 현재 코드 기준 미해결 항목이 아니다. 남은 판정은 G3 사람 수용, 실제 사이트 Fleet/로봇 readback, 물리 E-STOP·목표 이동, DEVICE/FIELD다. 이 문서의 최상위 판정은 그 게이트가 끝날 때까지 **HOLD (LOCAL)**로 유지한다.

## 2026-09-28 지도·카메라 반응형 및 제목 의미 보완

- 데스크톱에서는 현장 지도와 카메라 미리보기를 같은 카드 안에서 나란히 배치해 선언 뷰포트 1920×1080에 함께 들어오게 했다. 390px·320px에서는 세로 흐름을 유지하고, 16:9 카메라 프레임의 최소 높이가 가로 넘침을 만들지 않게 했다. `발견`, `대형`, `신호등`은 보조기기가 제목으로 탐색할 수 있도록 `h3`로 표시하면서 기존 글꼴·간격은 유지한다.
- 변경 후 `X:\DevTemp\rosy-uiux-d309-fleet-g2\capture_fleet_g2.py`를 현재 worktree 자산으로 실행해 8개 상태×3개 뷰포트 24셀과 첫 기동 3장을 다시 캡처했다. 상태 JSON 24셀 모두 pageerror 0·가로 넘침 0이고, 1920×1080에서 문서 세로 넘침도 없다. 모바일 세로 스크롤은 허용된다. 대표 데스크톱/320px 캡처를 육안 확인했다.
- Fleet Chromium·대화상자 시험 **32 passed**, Fleet 호스트 시험 **543 passed, 5 skipped**. 새 카메라 고장→IR 추적 확인을 취소하면 POST가 없다는 회귀도 포함한다. Docker Compose config와 `rosy-site-fleet:uiux-headings` 이미지 빌드가 통과했고, 컨테이너 내 CLI help를 실행했다.

이 결과는 SOURCE/LOCAL 증거다. Ubuntu 사이트 호스트, 실제 카메라·CORE·로봇 readback, 운영자 G3, DEVICE/FIELD는 별도 HOLD다. 임시 캡처는 X:에만 두며 제품 수용 근거로 합산하지 않는다.
