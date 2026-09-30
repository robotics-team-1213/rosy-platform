# emotion logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/emotion`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the emotion harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; `PYTHONPATH=src/emotion python3 -m pytest src/emotion/test/test_info_screen.py -q` 1 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): regrade emotion gates after review
- 변경: 2차 리뷰 반영. 이미지 제외 시험을 SOURCE에서 ARTIFACT 근거로 옮기고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로. 위 항목의 LOCAL 1 passed는 오기이며 같은 명령은 16 passed다
- 증거: `PYTHONPATH=src/emotion python3 -m pytest src/emotion/test/test_info_screen.py -q` 16 passed; `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed (2026-09-16 재실행, Windows는 `;` 구분자)
- gate 변화: SOURCE GO→HOLD, ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-21 · uncommitted · docs(uiux): emotion G1 fails on the current tree — regroup import mismatch (D-153 session 1, F-01)
- 변경: 없음(측정과 기록). D-153 회차1이 로봇 얼굴 G1을 재실행하다 발견. SOURCE/LOCAL GO를 HOLD로 정정하고 `progress.md` 지금 상태·다음 gate를 F-01에 맞게 갱신
- 증거: `python -m pytest src/apps/emotion/test/test_info_screen.py src/apps/emotion/test/test_info_screen_palette.py -q` → 수집 에러 2건(`ModuleNotFoundError: No module named 'emotion'`). `PYTHONPATH=src/apps/emotion` 재시도 동일. 렌더러 자체는 `PYTHONPATH=src/apps/emotion/emotion`에서 `from rosy_emotion.info_screen import DEFAULT_SIZE, battery_color, render` 정상(320×240). `emotion/__init__.py` 부재, `resource/`에 `emotion`·`rosy_emotion` 마커 공존
- gate 변화: SOURCE GO→HOLD, LOCAL GO→HOLD — 이전 GO(dc89264, 2026-09-17)는 재편(9b77daa, 2026-09-19) 이전 경로 `src/emotion`의 증거라 D-79 위반
- 결정: 수정은 모듈 세션 소유 — 테스트·`setup.py` entry_points를 `rosy_emotion.*`로 통일하거나 패키지명을 환원하고 마커를 같은 커밋에 정리한다. 기록: [D-153 회차1](../../docs/validation/uiux-surfaces-2026-09-21/README.md)
- 교훈: 재편 스윕이 "폴더 이동"은 하고 "import 표면"(테스트·entry_points·마커)은 못 끼고 가면 모듈 시험은 수집 단계에서 죽는다 — 이전 GO 기록이 그 죽음을 2일간 가렸다

## 2026-09-21 · uncommitted · fix(emotion): flatten the package to complete the regroup — F-01 closed (D-153 session 2)
- 변경: `emotion/rosy_emotion/{__init__,emotion_server,info_screen,rosy_lcd,rosy_emotion}.py`를 `emotion/`으로 평탄화하고 `rosy_emotion.py`는 `emotion.py`로 환원(setup.py entry_point `emotion=emotion.emotion:main`·AGENTS `emotion.py`가 문서화하던 재편 의도를 완성). 내부 import는 전부 상대경로(`.rosy_lcd`·`.info_screen`)라 무변경. 낡은 마커 `resource/rosy_emotion` 삭제, 두 AGENTS.md를 `emotion/AGENTS.md` 하나로 병합, 부모 AGENTS.md 하위 디렉터리 표·시험 명령 갱신
- 증거: `PYTHONPATH=src/apps/emotion python -m pytest src/apps/emotion/test/test_info_screen.py src/apps/emotion/test/test_info_screen_palette.py -q` → **22 passed** (2026-09-21 Windows, 수정 전 수집 에러 2건 → 수정 후 녹색 = mutation 방향 확인). `rosy_emotion` 잔여 참조 grep 0(문서 기록 제외)
- gate 변화: SOURCE HOLD→GO, LOCAL HOLD→GO — 현재 트리 재실행 증거(D-79)
- 결정: `rosy_emotion.*`로 통일하는 안 대신 재편이 선언한 `emotion.*` 평탄화를 택했다 — package.xml·setup.py·share 조회·AGENTS·테스트가 전부 `emotion`을 말하고 D-147이 `rosy_*` 패키지명을 금지한다
- 교훈: 반쪽 리팩터링의 잔해는 "선언은 새 것, 파일은 옛 것"의 모양으로 남는다 — 리팩터링 커밋은 자기가 선언한 import 표면을 실제 파일 구조와 같은 커밋에서 맞춰야 한다

## 2026-09-21 · uncommitted · fix(emotion): missing battery is '--', not a fake 0% alarm (D-153 session 4, F-04)
- 변경: `info_screen.render()` — `payload.get("battery_percent") or 0.0`이 결측과
  실측 0을 한데 묶어 결측 배터리를 crit 색 "0%" 위경보로 그렸다(Law 0 위반,
  같은 렌더러의 전압 `--` 폴백과 자기 모순). 결측은 `--`(muted), 실측 0%는
  여전히 crit로 분기. 회귀 시험
  `test_missing_battery_percent_is_not_a_critical_alarm` 신설
- 증거: `PYTHONPATH=src/apps/emotion python -m pytest src/apps/emotion/test/
  test_info_screen.py src/apps/emotion/test/test_info_screen_palette.py -q` →
  **23 passed**. mutation 방향 확인 — 수정 전 코드로는 새 시험이 적색(crit
  픽셀 존재). 재생성 캡처 `first-boot-empty`의 crit 픽셀 = 0(수정 전 위경보
  레드였음). flake8 0
- gate 변화: 없음(SOURCE/LOCAL GO 유지, LOCAL 증거 23 passed로 갱신)
- 결정: F-04의 나머지(증거 어휘 부재)는 결함이 아니라 얼굴 문법의 번역으로
  판정 — 웨이크 카드 `hold_s` 만료 소거. concept 16 §5에 얼굴 문단 명문화
- 교훈: `or 0.0` 폴백은 "값이 없다"와 "값이 0이다"를 같은 색으로 그린다 —
  경보 색이 붙은 필드의 폴백은 결측 표현이어야 하고, 같은 파일에 이미 옳은
  선례(전압 `--`)가 있으면 그 규약을 따른다

## 2026-09-21 · uncommitted · test(emotion): face captures are reproducible from the repo (D-153 session 6)
- 변경: `test/test_info_screen_capture.py` 신규(옵트인 — `ROSY_FACE_CAPTURE_DIR`
  가 가리키는 폴더에 웨이크 카드 4종 PNG 기록). 회차 2–4의 X:\DevTemp 임시
  스크립트 경로를 대체해 로봇 얼굴 G2 캡처가 저장소에서 재현된다. F-04 회귀
  단얜(결측 배터리 crit 픽셀 0)을 캡처 시험에도 동반
- 증거: `PYTHONPATH=src/apps/emotion ROSY_FACE_CAPTURE_DIR=docs/validation/
  uiux-surfaces-2026-09-21 python -m pytest src/apps/emotion/test/
  test_info_screen_capture.py -q` — 묶음 **24 passed**(info_screen 17·
  palette 6·capture 1), 카드 4종 320×240 재생성 확인
- gate 변화: 없음. LOCAL 증거 24 passed로 갱신
- 결정: 캡처 산출물은 docs/validation(저널)에 두고 생성 경로는 시험(저장소)이
  소유한다 — 임시 스크립트는 증거 체인에서 빠진다
- 교훈: 옵트인 캡처 시험은 침묵하지 않는다 — 재현 불가능한 캡처 절차는 시험이
  될 때 비로소 회차 기록이 된다

## 2026-09-21 · uncommitted · feat(emotion): render operator-assistance request on the robot face

- 변경: `display/info`의 `hitl_requested`가 참이면 HEALTH 행에 `ASSIST REQ`를 표시한다. E-STOP이 동시에 참이면 안전 상태가 우선한다.
- 증거: `test_info_screen.py` 19 passed; normal/HITL 이미지 차이와 E-STOP 우선순위를 픽셀 비교로 검증했다.
- gate 변화: SOURCE/LOCAL GO 유지. 실제 LCD DEVICE 증거는 PARKED다.
- 결정: D-999.

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# emotion logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/emotion`를 본다.

## 2026-09-24 · uncommitted · feat(emotion): stage-aware boot card for the LCD (D-190 S2)

- 변경: `info_screen.render_boot`/`boot_lines` 추가. 부팅 표시(`rosy-boot-display`, CORE 밖)가 쓰는 320x240 카드: 이름, 릴리스,
  단계(FAILED 빨강 + 실패 unit), `IP:포트`, 배터리, AP SSID·비밀번호. D-82 팔레트, 긴 문자열은 줄이고 최소 글꼴 아래에서만 자름.
  기존 `render`(얼굴의 정보 카드)는 그대로. 얼굴 자체는 여전히 벤치 전용(D-169)
- 증거: `python -m pytest src/apps/emotion/test -q` 43 passed, 4 skipped(2026-09-24 Windows), 부팅 카드 시험은 WSL(DejaVu)에서도 통과
- gate 변화: 없음
- 결정: D-190
- 교훈: 없음


## 2026-09-24 · uncommitted · fix(emotion): 경보 문장은 채움이다 — 얼굴 번역 (D-202)

- 변경: info_screen.py에 _draw_alarm 추가 — 웨이크 카드의 E-STOP 문장·위험 배터리 숫자, 부팅 카드의 FAILED·실패 유닛·코드 소각 문장을 crit 글자(어두운 바탕 위 2.2:1)에서 위험 채움+종이 잉크 칩으로. 배터리 게이지 봉은 이미 채움이라 그대로. 칩 하단 여백은 2px — 다음 줄 영역(부팅 카드 y=100 경계 계약)을 침범하지 않는다.
- 증거: PYTHONPATH=src/face/emotion python -m pytest src/face/emotion/test -q → 47 passed(칩 픽셀 게이트 3종 + 정상 무색 게이트 신설, 변이 증명: 칩을 crit 글자로 되돌리면 3종 적색).
- gate 변화: 얼굴 G1에 경보 침 픽셀 게이트·정상 무색 게이트 추가.
- 결정: D-202(얼굴 번역 문단)
- 교훈: 팔레트가 옳아도 칠하는 방식이 틀리면 경보는 여전히 안 읽힌다 — 값의 게이트와 용법의 게이트는 다르다.


## 2026-09-25 · uncommitted · test(emotion): 웨이크 카드 어휘 고정 (D-221, F-07 처분)

- 변경: test_info_screen.py 에 두 계약 추가 — 행 라벨(MODE·NAV·HEALTH) 고정, 렌더러 폰트 의존 금지(DejaVu 후보만, CJK 경로 금지). 변이 증명: MODE→모드 교체 → 적색.
- 증거: PYTHONPATH=src/face/emotion python -m pytest src/face/emotion/test -q → 49 passed.
- gate 변화: 얼굴 G1에 어휘·폰트 계약 추가.
- 결정: D-221
- 교훈: 보류된 결정도 저장소 안 사실(폰트 부재, enum 값)으로 닫을 수 있을 때가 있다 — 하드웨어가 유일한 입력이라는 가정을 먼저 검증하라.

## 2026-09-25 · uncommitted · refactor(hmi): move emotion under src/hmi (D-231)

- 변경: src/hmi/emotion로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 hmi 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(emotion): D-260 boot card state line and top todo
- 변경: `info_screen.py` 부팅 카드에 `robot_state`(154, 16)·`todo`(176, 15) 줄. AP 줄은 할 일 자리를 쓰고 한 칸씩 내려감(login 218+18 ≤ 240)
- 증거: `python -m pytest src/hmi/face/test/test_info_screen_boot.py -q` 29 passed; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: DejaVu에 한글이 없어 LCD는 같은 규칙의 영어 짧은 말을 쓴다

## 2026-09-27 · uncommitted · fix(emotion): D-306 정보 카드 긴 문자열 경계

- 변경: `render()`의 로봇 ID·MODE/NAV/HEALTH 값·주소에 부팅 카드의 기존 `_fit`을 적용해 320×240 경계에서 말줄임과 16px 오른쪽 여백을 유지한다. E-STOP 경고·색·AP QR 배치는 그대로 둔다.
- 증거: Windows ROS-free PIL 시험 128 passed, 캡처 시험 1 passed. `X:\DevTemp\rosy-uiux-lcd-2026-09-27`에 부팅/AP QR/실패/긴 문자열 및 wake 카드 4종 PNG 320×240을 생성하고 시각 확인했다.
- gate 변화: SOURCE/LOCAL GO의 증거 갱신. DEVICE/BENCH와 FIELD는 실물 사진·거리·각도·조명 관찰이 없어 승격하지 않는다.
- 결정: D-306, D-153.

## 2026-09-27 · uncommitted · fix(face): 웨이크 카드 중 power/mode 전환 유예 (D-309)

- 변경: `display/info` 카드가 살아 있는 동안 새 `power/mode`는 최신 값으로 저장하되 백라이트·sleep 전환을 카드 만료까지 유예한다. 만료 시 저장된 idle/standby 모드를 적용한다.
- 증거: 실제 `display_info_callback`→`power_mode_callback`→`timer_callback`를 ROS/LCD stub으로 연결한 시험은 수정 전 idle dim·standby sleep으로 적색, 수정 후 face 160 passed/4 skipped와 공유 색 계약 19 passed. `X:\DevTemp\rosy-uiux-lcd-card-mode\`에 카드 유지/만료 후 의도 화면 LOCAL PIL 캡처를 생성했다.
- gate 변화: SOURCE/LOCAL 회귀 근거 추가. 실제 Pi 백라이트, 화면 판독, 만료 전환은 DEVICE/BENCH HOLD.
- 결정: D-309, D-153.

## 2026-09-27 · uncommitted · fix(face): E-STOP 정보 카드의 우선순위와 배터리 줄

- 변경: 320×240 웨이크 카드에서 E-STOP일 때 큰 위험색 채움 경보를 상단 주시 영역에 놓고, 측정 배터리·전압을 게이지 위의 별도 줄에 보존한다. 정상 카드와 기존 D-280/D-202 상태색은 유지한다.
- 증거: 상단 경보와 저전압/결측 배터리 줄의 적색→녹색 회귀; ROS-free 관련 시험 162 passed. `X:\DevTemp\rosy-lcd-visual-g3\`의 before/after 정상·E-STOP·E-STOP 저전압 PNG를 320×240에서 대조했고 정상 카드는 픽셀 동일했다.
- gate 변화: SOURCE/LOCAL 검증 근거 추가. 실제 Pi LCD의 거리·각도·조명 판독은 DEVICE/BENCH HOLD.
- 결정: D-280, D-306, D-309.

## 2026-09-29 · uncommitted · fix(face): ASSIST REQ renders as a warn-filled chip (P4 round)

- 변경: 웨이크 카드 HEALTH 행의 ASSIST REQ(사람 개입 요청)가 평문이어서 OK와 같은 무게로 읽혔다. `_draw_caution`(warn 채움 + ground 잉크)을 추가해 crit 칩과 형태가 같고 색만 다른 어휘로 정리했다(8항 위계).
- 증거: face 시험 162 passed / 4 skipped. PIL 렌더 11장(웨이크 7 + 부팅 4) 0.5초 판독 독회 — `X:\DevTemp\rosy-uiux-p4-lcd`. 회차 기록은 `docs/validation/uiux-surfaces-2026-09-29/README.md` P4 절.
- gate 변화: 없음. SOURCE/LOCAL GO 유지. Pi 실물 폰트·거리·각도·조도·만료 복귀는 미측정이며 표면은 BENCH/DEVICE HOLD다.

## 2026-09-30 · uncommitted · docs(harness): ROS-SIM blocker를 실제 조건으로 정정

- 변경: ROS-SIM blocker가 "Jazzy 컨테이너 재실행 필요"라고만 적혀 있었다. 실제 조건을 적었다: emotion.py는 모듈 최상위에서 `from .rosy_lcd import LCD`를 부르고 rosy_lcd는 spidev·RPi.GPIO를 최상위 import한다 — Pi가 아닌 컨테이너에서는 노드 import 자체가 죽는다. 컨테이너 smoke는 하드웨어 import 지연/가드 리팩터가 선행 조건이며, 그것 없이 Pi에서만 가능한 검증은 DEVICE 계층이다.
- 증거: 소스 대조 — emotion.py:8 `from .rosy_lcd import LCD`, rosy_lcd.py:1-3 `import spidev`·`import RPi.GPIO as GPIO` (모듈 최상위).
- gate 변화: 없음 (HOLD 유지, blocker 사유만 정확화).
- 결정: 없음.
- 교훈: led의 rosylib 경우와 같은 모양이다 — "컨테이너에서 돌려라"가 유효한 지시인지는 노드의 import 그래프가 결정한다. blocker를 쓸 때 import 경로를 먼저 본다.
