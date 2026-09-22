## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


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
