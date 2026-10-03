---
module: pilot
logical_modules: []
owner: 화면
last_verified: { commit: "10daaae5", date: 2026-10-02 }
gates:
  SOURCE:
    state: GO
    evidence: "T1 /pilot 라우트 계약 2 passed·T3 stick 매핑 8 passed·api_web 전체 72 passed·web_common known_failures 0 new (2026-09-29 Windows)"
    cmd: "python -m pytest src/hmi/pilot/test src/runtime/api_web/test/test_pilot_route.py -q -p no:cacheprovider"
  LOCAL:
    state: HOLD
    blocker: "OMX 페어링→조그와 Pinky 게이트 브라우저 시험은 각각 통과. 기록 시작 실패·재시도·결과·stale 영상·dispose Chromium 시험과 실제 Gazebo 15프레임→LeRobot 재독출은 통과. 전체 Pilot/Pinky 경로 재측정은 남음"
    cmd: "python -m pytest src/hmi/pilot/test/test_pilot_browser.py -q -p no:cacheprovider"
  ROS-SIM:
    state: HOLD
    blocker: "OMX 관절·그리퍼·취소의 Gazebo action/readback은 docs/validation/pilot-omx-gazebo-2026-10-01/에서 확인. Gazebo 작업대 영상·시연 기록 15프레임과 실제 LeRobot v3 재독출도 통과. 그리퍼 정밀 도달·전체 재시작 회복·Pinky 재측정은 남음"
  ARTIFACT:
    state: HOLD
    blocker: "share/pilot 설치를 이미지에서 본 기록이 없다"
  DEVICE:
    state: HOLD
    blocker: "실기 Pinky 에서 페달 hold-해제가 실제 정지로 이어지는 확인 전"
  FIELD:
    state: N/A
adrs: [D-323, D-365, D-366, D-390, D-411]
plans:
  - docs/plans/2026-10-01-omx-demonstration-lerobot-design.md
  - docs/plans/2026-09-29-rosy-pilot-teleop-app-design.md
  - docs/plans/2026-09-29-rosy-pilot-teleop-app.md
  - docs/plans/2026-10-01-pilot-omx-gazebo-practice.md
  - docs/plans/2026-10-02-d411-pilot-recording-controls-plan.md
---

## 지금 상태

- 골격 착지: `/pilot` 라우트·web_common ui-shell 표면·`stick.js` 순수 입력 매핑.
- 앱은 같은 출처의 `/api/v1`·`/ws/*` 만 말한다(D-323, CORE SRS §1.3).
- 1차 기기는 현장 태블릿(Lenovo 1200×2000) — 가로 모드 기준 레이아웃.

- 2026-09-29 가제보 실조종 교정: 부호 규약(REP-103)·2 축 스틱·제자리 회전·CORE 한도 비율 프리셋·송신 타이밍. 팔은 조작 프로필 `arm` 설계만(계약 대기).
- 2026-10-02 D-411 B: 화면은 기기가 알리는 `rosy.controls/1` 로 조립된다(주행 `base_velocity`, OMX SIM `joint_jog` 조이스틱). 브라우저 시험 통과, OMX Gazebo 에서 조이스틱은 아직 미실행(ROS-SIM HOLD).

## 다음 gate

1. LOCAL: 실행 계획 T11 Playwright 종단(가짜 CORE) 통과 뒤 GO.
2. ARTIFACT: 이미지 closure 에 pilot 패키지 포함 확인.
3. DEVICE: 실기 Pinky 주행 확인(증거는 `docs/validation/pilot-<date>/`).
