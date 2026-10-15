# OMX AI Hardware Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** OMX AI의 실물 요청→단일 local owner→vendor controller→물리 feedback→정지/복구→결과 readback을 완성하고, 검증된 조건에서 딸기 왕복을 수행한다.

**Architecture:** [실물 제어 설계](2026-10-15-omx-hardware-control-design.md)의 기존 owner/ROS/UDS/원장을 재사용한다.
SIM profile·SIM gripper·SIM API는 실물에서 재사용하지 않는다. 현장 OS/ROS 호환성과 물리 측정은 독립 관문이다.

**Tech Stack:** 기존 Python·ROS 2·ros2_control·고정 ROBOTIS source·native systemd·Fleet/Pilot.
지원 배포판 변경과 실물 API는 구현 전에 ADR·공유 schema·API reference로 확정한다.

## G1. 현재 단절을 실제로 재현한다

**Files:** `deploy/robot/omx/hardware_readiness.py`, `test/test_omx_hardware_readiness.py`, deployment README.

1. 카메라-only·다른 distro·synthetic state·잘못된 Action type·다른 cell 혼합에 대해 실패하는 시험을 커밋한다.
2. 원격 RED를 확인하고 읽기 전용 discovery/순수 판정을 구현한다.
3. 올바른 software positive control에서도 motion=false임을 확인하고 원격 GREEN·known_failures를 기록한다.
4. 현장 기본 환경에서 진단을 실행한다. 설치·bus open·torque·goal 없이 누락을 읽는다.

**종료:** 실제 누락과 진단의 positive/negative 시험이 일치한다. 실물 제어 완료로 표시하지 않는다.

## G2. 실제 host의 vendor stack을 비구동 검증한다

**Files:** 기존 `stack.lock.yaml`, `fetch_sources.py`, vendor patch 검사·build 경로.

1. native OS/ROS/Python·필수 패키지·빌드 자원과 기존 overlay를 확인한다.
2. 고정 source를 별도 build 공간에서 Lyrical에 compile/link 검사한다. source lock은 유지한다.
3. 기존 Jazzy와의 차이, API/ABI·driver lifecycle·자동 동작을 검토한다. 지원 변경이 가능하면 ADR와 설치 계약을 먼저 확정한다.
4. 호환되지 않으면 native Jazzy 제어 host/운영 host 재구성 중 실제 실행 가능한 방안을 구체화한다. 운영 OS를 자동 교체하지 않는다.

**종료:** 선택 runtime에서 controller/driver가 비구동 시험으로 검증되고 immutable artifact·설치 receipt가 있다.

## G3. 측정 profile과 독립 stop을 닫는다

**Files:** 기존 D-496 설계의 hardware profile loader·비공개 실측 config·adapter profile tests.

1. 두 OpenRB의 역할을 물리 연결과 대조한다. 이름 순서/tty 번호로 follower를 선택하지 않는다.
2. 기존 B0–B7에 따라 joints·단위·한계·속도·gripper jaw·부하·workspace·기구/보정 revision을 측정한다.
3. 통신/전원 상실·driver 재시작·처짐과 독립 stop을 감독하에 검증한다. E-stop 재설정·torque-off를 임의 실행하지 않는다.
4. 누락·SIM revision·단위/순서/한계 불일치·재시작 미확인을 거절하는 loader/owner 시험을 작성한다.

**종료:** 실측값과 검수자가 있고 rig/profile/stop evidence가 일치한다. 구조화된 YAML만으로 물리 수용을 만들지 않는다.

## G4. 실물 local owner와 native instance를 연결한다

**Files:** 기존 `omx_cell_owner.py`, `ros_runtime.py`, action/store/stop/acceptance 경로와 별도 hardware composition/entrypoint.

1. SIM에 고정된 clock·identity·gripper source를 분리하되 기존 SIM caller/fixtures 동작을 보존한다.
2. 실측 profile·단일 bus/graph writer·실제 publisher provenance·steady clock·독립 stop에 binding한다.
3. 재시작은 HOLD, 미해결 action을 재전송하지 않으며 취소 접수/terminal/실제 정지를 구분한다.
4. native systemd 인스턴스에 비공개 config·runtime dir·UID·instance ownership을 설정하고 no-goal 기동부터 검증한다.

**종료:** stale·late UUID·timeout·duplicate·source spoof·storage/stop fault를 원격/ROS 시험과 실제 readback으로 검증했다.

## G5. Fleet/Pilot 실물 계약과 UI를 연결한다

**Files:** API reference·`core_common.protocol.schemas`, 기존 Fleet Cell/admission, 별도 Pilot hardware driver 및 전체 asset/Android 등록.

1. 기존 UDS identity/admission과 source 권한을 대조해 hardware 계약을 ADR로 확정한다.
2. SIM `simulation:true` guard를 유지하고 실물 driver가 accepted instance에만 접근하도록 한다.
3. 접수→UUID→실제 feedback→종단→독립 outcome을 화면·원장에서 확인한다. 오류/권한/정지/재개 경로도 실제 브라우저로 확인한다.

**종료:** 버튼 표시와 응답 200 외에 실제 action/owner/원장 readback과 실패 복구가 있다.

## G6. 교육 과제를 실제로 닫는다

**Files:** 기존 episode/recording/task outcome과 물체 context v4, 새 dated validation.

1. 선정 pixel 구역의 camera-to-arm/TCP·workspace/장애물·딸기 하중/형상·용기 내부·임시 놓기 안정성을 검증한다.
2. 감독 조건에서 한 단계씩 꺼냄→임시 놓기→복귀를 실행하고 새 영상·관절·action/stop/결과를 묶어 읽는다.
3. 전체 cycle·실패·미판정·개입을 기록하고 IL split은 parent cycle을 넘나들지 않는다.

**종료:** 사용자 과제의 독립 물리 수용이 있다. 모델 동의·동결 이미지·SIM 성공으로 대체하지 않는다.

## 상태와 검증 규칙

- G1 완료: 원격 RED→GREEN·독립 재검토·현장 negative readback. 관련 원격 60시험 통과·NEW 0.
- G2 부분 진행: 고정 벤더 8패키지와 adapter 1패키지의 Lyrical private native build 성공,
  controller 4개 패키지 private extraction·핵심 라이브러리 2개 `ldd` 누락 0.
  지원 runtime/설치 승인·lifecycle/실물 시험은 미완료다. 시스템 패키지·서비스는 변경하지 않았다.
- G3–G6 미완료. follower 역할·실측 profile·독립 정지·보정이 없어 driver activation·명령은 실행하지 않았다.
  전체 목표는 아직 완료가 아니다. [직접 증거와 재개 조건](../validation/omx-hardware-control-preparation-2026-10-15/result.md).
- pytest는 커밋된 HEAD를 `tools/remote/remote_pytest.py`로 원격 실행하고 `test/known_failures.py`로 비교한다.
- stage마다 실제 source·테스트·runtime·물리 증거를 따로 기록한다. 관련 safety 경로 변경은 독립 리뷰를 받는다.
- 사용자가 승인한 로컬 병합까지 진행하며 push는 하지 않는다. 다른 세션의 WIP를 보존한다.
