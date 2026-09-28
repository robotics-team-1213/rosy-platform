# D-306 게임 보드 G2/G3 회차 — 2026-09-27

**표면·질문:** 노트북 게임 호스트의 1280×800 경기 보드. 심판이 경기 단계·점수·유실과 정지 요청 결과를 즉시 읽고 정지할 수 있는가. **판정: HOLD.** 아래는 Windows Chromium과 실제 `PreviewServer`/`PreviewBoard` 자산을 통한 LOCAL 증거이며, 로봇·카메라·현장 증거가 아니다.

> 아래 D-306 표와 첫 D-309 메모는 당시 기준의 기록이다. 현재 D-309 코드와 13셀 재촬영 결과는 문서 끝의 **현재 재평가**가 정본이다.

## 재현과 캡처 범위

- 기준: `main` `ca3b3869`으로 rebase한 `feat/games-board-ux`의 후속 게임 변경. 픽스처 실행기는 `X:\DevTemp\rosy-uiux-d306-games-g2\capture_games.py`, 결과는 같은 폴더의 `measurements.json`과 PNG 10개다. 스크린샷은 F:에 복사하지 않았다. X:의 일회성 파일이 사라지면 이 표의 이미지는 재생성해야 하며 보존형 G2 증거로 세지 않는다.
- 픽스처는 실제 `games.host.preview.PreviewServer`에서 HTML/CSS/JS와 `/overlay.json`을 서빙한다. 정상/유실 페이로드는 `test/test_games_board_browser.py`의 경기 fixture를 쓴다. HTTP 403/503, 무응답은 Playwright 라우트 또는 브라우저 fetch stub이다. 이 응답은 실제 호스트 권한·장치 실패를 재현한다고 주장하지 않는다.
- 각 셀에서 1280×800 `scrollWidth - innerWidth`, `scrollHeight - innerHeight`, `#halt` 위치, 활성 요소와 pageerror를 계측했다. **10셀 모두 가로/세로 넘침 0, pageerror 0, `#halt` 하단 최대 772px(<800px)** 이다. `02_normal_focus.png`에서 Tab 포커스 링을 육안 확인했고, 정지 요청 완료·실패·시간 초과 뒤 포커스 복귀는 브라우저 시험으로 고정했다.

| G2 셀 | 보이는 결과와 입력 | LOCAL 캡처 |
|---|---|---|
| 최초 기동 / 미수신 | 단계 `대기`, 점수 `—/—`, `경기 데이터 대기 중`; 실제 점수 0을 꾸미지 않음 | `01_initial.png` |
| 정상 수신 (`fresh` 경로) | `경기 진행`, 2:1, 로봇·공·마커·정지 버튼. Tab이 `#halt`에 닿고 링이 보임 | `02_normal_focus.png` |
| 데이터 없음 (`unavailable`) | 정상 수신 뒤 `{}` 응답 시 점수 2:1을 보존하되 `경기 데이터 대기 · 마지막 경기 정보`와 보조기기 안내를 표시 | `03_data_wait_after_play.png` |
| 연결 오류 (`disconnected` 경로) | 마지막 수신 뒤 overlay HTTP 503. `호스트 연결 오류 · 마지막 경기 정보`, 보조기기에도 마지막 수신 값으로 안내 | `04_disconnected.png` |
| 경기 `hold` / 유실 | `경기 보류`, `공을 잃음 · HOLD`, 마커 0; 정지 버튼은 화면 안 | `05_hold.png` |
| 정지 거부 모의 / 오류 | `/stop` HTTP 403은 실패·재시도 문구를 표시. 실제 PreviewServer에는 인증·403 경로가 없어 권한 수용 증거는 아님 | `06_stop_refused_403.png` |
| 정지 실패 | `/stop` HTTP 503은 실패·재시도를 표시하며 버튼을 다시 쓸 수 있음 | `07_stop_failure_503.png` |
| 정지 접수 | `/stop` HTTP 200은 `정지 요청 접수 · 실제 정지 확인 중`으로 표시. 장치 정지 완료 문구는 아님 | `08_stop_accepted.png` |
| 정지 응답 대기 | 무응답 요청은 `정지 요청 중`과 버튼 비활성을 표시 | `09_stop_pending.png` |
| 정지 시간 초과 | 5초 뒤 `시간 초과 · 다시 눌러 재시도하세요`; 버튼과 키보드 포커스를 복원 | `10_stop_timeout.png` |

**빠진 셀과 N/A 근거:** `delayed`는 **미평가 blocker**다. `overlay_payload()`는 수신/생성 시각이나 증거 연령을 제공하지 않아 응답 HTTP 200이 오래된 프레임인지 판정할 수 없다. 빈 로봇 등록 목록은 이 보드에 없는 개념이라 N/A이고, 유실·마커 0은 위 `hold` 셀에서 확인했다. 게임 `Phase`는 `kickoff/play/hold/goal`만 가지므로 `SAFE_STOP` 이름의 게임 상태는 N/A다. 위 `hold`는 경기 판정이지 CORE의 안전 정지 readback이 아니다. 확인 대화상자는 D-218·D-253의 게임 즉시 정지 예외로 N/A다. 실제 PreviewServer의 권한 거부도 N/A이며 HTTP 403은 화면 실패 표현만 시험했다.

## D-153 G3 여덟 항

| 항목 | 코드·셀 근거 | 평가 |
|---|---|
| 1. 정직 | 최초 점수 `—`; 데이터 대기·연결 오류는 마지막 정보임을 밝힘. `/stop` 200을 장치 완료로 쓰지 않음. `#stair1`은 `FIELD GO 아님`을 유지 | LOCAL 충족. 물리 정지는 미확인 |
| 2. 증거 상태 | 정상, 데이터 없음, HTTP 오류를 구분하며 `role=status`는 단계·점수·유실이 바뀔 때만 갱신. 응답 시간/증거 나이가 없어 `delayed` 판정 불가 | **HOLD** |
| 3. 색 | 위험한 정지 버튼과 유실은 붉은 색, 데이터·상태는 글자로도 구분. 다만 기존 공의 주황색과 원정 팀의 분홍색은 D-153 Law 1의 “경보 밖 따뜻한 색 없음”을 문자 그대로 적용하면 충돌한다. 경기 물체 식별 색의 예외 범위가 결정되지 않음 | **HOLD** |
| 4. 위계 | 점수→피치→가시성/유실→정지 순서. 정지는 별도 채움 버튼이며 10셀에서 접힘 위, `hold`에서도 하단 772px | LOCAL 충족 |
| 5. 불가역 | D-218·D-253은 게임 정지를 확인 없는 즉시 조작으로 명시. 클릭/Space가 같은 `/stop`을 한 번 보내며 실패 뒤 재시도 가능 | 계약 충족; 물리 정지 미검증 |
| 6. 어휘 | 단계 `경기 진행`/`경기 보류`, `홈`/`원정`, 유실·연결·정지 결과는 한국어 평문. 로봇 ID와 `FIELD GO`는 운영 식별자·게이트 표기 | LOCAL 충족 |
| 7. 표면 질문 | 정상/유실/정지 결과·실패 10셀에서 단계·점수·필드·다음 정지 조작이 보임. 카메라·마커의 실제 판독성과 로봇 반응은 확인 안 됨 | LOCAL 충족, FIELD 미평가 |
| 8. 표면 문법 | 단일 피치 중심 화면, 모든 캡처에서 넘침 0·정지 접근 가능. `#halt` 포커스 링과 완료 후 복귀 확인 | LOCAL 충족 |

G1 관련 게임 호스트·공용 UI·대화상자·문법 시험은 168 passed, 브라우저 11 passed, gateway 증거 시험 7 passed였다. **G2의 `delayed` 셀과 G3 색 예외 판단이 남아 표면 GO를 선언하지 않는다.** DEVICE/FIELD는 실제 천장 카메라, 로봇, 물리 정지 확인 전까지 PARKED다.

## 2026-09-27 D-309 게임 보드 시간 증거 보완

- `PreviewBoard.publish()`가 실제 보드 갱신의 UTC `generated_at`과 monotonic 시각을 기록한다. `/overlay.json`은 서버 시계로 `age_s`, `stale_after_s=2.0`, `evidence`를 반환하며 반복 조회만으로 시각을 새로 만들지 않는다.
- 보드는 서버가 판정한 `delayed`와 마지막 생성 경과 시간을 표시한다. HTTP 실패는 별도 연결 오류로 유지한다. 팀 구분의 분홍색은 차분한 회청색으로 바꾸고 공의 주황색은 D-309의 경기 데이터 예외로 유지했다.
- 검증: 게임 서버 102 passed, 브라우저 12 passed (Windows LOCAL). 위 10개 PNG는 변경 전 기록이다. 새 시각 캡처, 실제 카메라·로봇·정지 증거는 HOLD다.

## 현재 재평가: D-309 통합 후 LOCAL 13셀

기준은 `main` `f286e298`에서 분기한 게임 전용 worktree다. `X:\DevTemp\rosy-uiux-d309-games-g2\capture_games.py`가 실제 `PreviewServer` 자산을 1280×800 Chromium에 서빙해 `measurements.json`과 PNG를 만든다. 생성 시각은 `PreviewBoard`의 고정 monotonic clock을 조정하여 `fresh`→`delayed`를 재현하고, HTTP 403/503과 무응답은 Playwright fixture로 주입한다. **13셀 모두 가로·세로 넘침 0, pageerror 0**이다. 정상 화면에서 Tab 포커스가 정지 버튼에 닿고, 정지 결과·시간 초과 뒤 다시 버튼으로 돌아온다. X: 캡처는 일회성이며 저장소의 보존형 이미지가 아니다.

| G2 셀 | 화면·보조기기 결과 | 캡처 파일 (위 X: 폴더) |
|---|---|---|
| 최초 기동 / 미등록에 해당하는 미수신 | `대기`, 점수 `—/—`, `경기 데이터 대기 중`; `unavailable` | `01_initial.png` |
| 정상 `fresh` | `경기 진행`, 2:1, 피치/마커, `호스트 연결됨`, 정지 버튼 포커스 링 | `02_normal_focus.png` |
| `delayed` | 서버 판정과 `마지막 생성 3.0초 전`을 표시하고 한 번만 보조기기에 알림 | `11_delayed.png` |
| 데이터 없음 `unavailable` | 이전 점수를 보존하되 `경기 데이터 대기 · 마지막 경기 정보`와 보조기기 마지막 수신 안내 | `03_data_wait_after_play.png` |
| 시각 필드가 없는 이전 응답 | 점수는 표시하되 `시각 정보 없음 · 마지막 경기 정보`; `fresh`를 꾸미지 않음 | `13_missing_time_evidence.png` |
| 전송 실패 `disconnected` | HTTP 503 뒤 `호스트 연결 오류 · 마지막 경기 정보` | `04_disconnected.png` |
| 첫 전송부터 실패 | 점수 `—/—`와 `호스트 연결 오류 · 경기 정보 없음` | `12_first_error.png` |
| 경기 `hold` / 유실 | `경기 보류`, `공을 잃음 · HOLD`, 마커 0 | `05_hold.png` |
| `/stop` 403 거부 fixture | 실패·재시도; 실제 게임 서버 권한 정책의 증거는 아님 | `06_stop_refused_403.png` |
| `/stop` 503 오류 fixture | 실패·재시도 | `07_stop_failure_503.png` |
| `/stop` 200 접수 fixture | `정지 요청 접수 · 실제 정지 확인 중`; 물리 정지 완료라고 하지 않음 | `08_stop_accepted.png` |
| 정지 요청 무응답 | 요청 중 상태와 일시 비활성 | `09_stop_pending.png` |
| 정지 요청 시간 초과 | 5초 뒤 재시도와 포커스 복귀 | `10_stop_timeout.png` |

G2 적용 경계: 게임 `Phase`에는 CORE `SAFE_STOP`이 없고 경기 `hold`는 그 대체 증거가 아니다. 게임 보드는 로봇 등록 목록이 없으므로 빈 등록 목록 셀은 N/A이며, 미수신·마커 0은 위에서 확인했다. PreviewServer는 인증/권한 거부 경로가 없어 403은 화면 실패 처리 fixture로만 평가한다. D-218·D-253에 따라 게임 정지는 확인 없는 즉시 조작이므로 네이티브 confirm 셀은 N/A다. `/overlay.json` 전송 오류는 호스트가 판정한 경기 데이터 지연과 구분한다.

### 현재 G3 8항

| 항목 | 현재 근거 | LOCAL 평가 |
|---|---|---|
| 정직 | 최초 점수 `—`, 시각 없는 응답 `unavailable`, 첫 오류 `경기 정보 없음`, 정지 200은 접수로만 표현, `FIELD GO 아님` 유지 | 충족 |
| 증거 상태 | `PreviewBoard.snapshot()`이 생성 나이를 판정하고 4개 화면 경로가 분리된다. 지연은 나이를 보여주며 보조기기에는 첫 전환에만 읽힌다 | 충족 |
| 색 | D-309가 공의 주황색을 피치의 단일 데이터 표식 예외로 확정했고 원정 팀은 회청색으로 바뀌었다. 위험/유실 붉은색은 형태·문구와 함께 사용 | 충족 |
| 위계 | 점수→피치→유실/가시성→별도 채움 정지 순서, 13셀 모두 정지 접근 가능 | 충족 |
| 불가역 | D-218·D-253의 게임 즉시 정지 예외. 클릭/Space 동일 경로, 대기·실패·접수·시간 초과와 포커스 복귀 시험 | 계약 충족; 물리 결과 미평가 |
| 어휘 | 단계·오류·다음 조치는 한국어 평문, 로봇 ID와 `FIELD GO`는 운영 식별자·게이트 표기 | 충족 |
| 표면 질문 | 13셀에서 단계·점수·필드 또는 결측·정지 조작 결과가 보임 | LOCAL 충족; 실물 경기 미평가 |
| 표면 문법 | 단일 피치 중심, 13셀 1280×800 가로·세로 넘침 0, 키보드 정지 포커스 확인 | 충족 |

게임 브라우저 14 passed, 게임 호스트·공용 UI/대화상자/문법/증거 계약 176 passed. 추가한 이전 응답 fixture는 시각 필드가 빠져도 `fresh`로 거짓 승격하지 않는 것을 고정한다. **LOCAL에서 재현 가능한 G2 셀과 G3 위반은 닫혔다.** D-153의 보존형 화면 증거는 X:의 일회성 캡처가 사라지면 재생성이 필요하므로 표면 최종 GO로 승격하지 않는다. 실제 카메라·로봇 경기, 양쪽 로봇의 물리 정지 readback, DEVICE/FIELD 수용도 여전히 HOLD다.

## 2026-09-28 최신 main 재검증

`main` `757fb38f`의 화면 자산으로 LOCAL 재검증했다. `python -X utf8 -m pytest src/site/games/test test/test_rosy_games_surface.py -q`는 **111 passed**, `ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest test/test_games_board_browser.py -q`는 **15 passed**다. 기존 `X:\DevTemp\rosy-uiux-d309-games-g2\capture_games.py`를 최신 main에서 다시 실행해 13셀 PNG와 `measurements.json`을 갱신했다. 캡처는 1280×800이며 13셀 모두 가로·세로 넘침 0, `pageErrors` 빈 배열이다. `delayed`, `disconnected`, 데이터 없음/시각 없음 셀은 마지막 수신 점수·단계를 보존하고 현재 위치가 아님/결측 상태를 화면에 드러낸다. `delayed`와 포커스 링, 연결 끊김, 시각 정보 없는 응답 화면을 육안 확인했다.

이 검증은 로컬 Chromium·fixture 범위다. 실제 카메라/경기, CORE 물리 정지 readback, 사람 G3, DEVICE/FIELD는 여전히 HOLD다. 캡처는 X: 임시 산출물이므로 사라지면 재생성해야 하며, 보존형 릴리스 근거로 취급하지 않는다.
