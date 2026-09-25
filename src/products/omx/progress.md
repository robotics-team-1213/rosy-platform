---
module: omx
logical_modules: []
owner: 로봇 통합
last_verified: { commit: "uncommitted", date: 2026-09-25 }
gates:
  SOURCE:
    state: GO
    evidence: "omx.disabled.yaml이 어댑터 패키지에서 이 설정 패키지로 옮겨졌고, enabled false·빈 모델 시험이 통과 (2026-09-25)"
    cmd: "python -m pytest src/products/omx/test -q"
  LOCAL:
    state: GO
    evidence: "같은 호스트 시험이 이 파일을 읽고 통과 (2026-09-25 Windows)"
    cmd: "python -m pytest src/products/omx/test src/devices/omx/adapter/test -q"
  ROS-SIM:
    state: HOLD
    blocker: "colcon으로 share/omx/config 설치를 본 기록이 없다"
  ARTIFACT:
    state: HOLD
    blocker: "io 이미지가 이 패키지를 포함한 뒤의 package inventory가 없다"
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-196, D-231, D-232]
plans: []
---

## 지금 상태

- 팔 설정은 여기 있다. 어댑터 코드는 `src/devices/omx/adapter`다.
- 모델은 비어 있다. `omx-f`와 `omx-ai`는 측정 뒤에 고르는 이름이다.

## 다음 gate

1. ROS-SIM: `colcon build --packages-select omx` 뒤 `share/omx/config/omx.disabled.yaml`이 설치된다.

## 현재 유효한 금지사항

- 이 폴더에 Python 실행 코드나 launch를 두지 않는다.
- `hardware_plugin`을 가짜 값으로 채우지 않는다.
