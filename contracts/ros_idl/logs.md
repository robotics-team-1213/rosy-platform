# interfaces logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/interfaces`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the interfaces harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: repo `test/`에서 `interfaces`·`Emotion.srv`·`SetLed.srv`·`SetLamp.srv`·`SetBrightness.srv`를 grep — srv 스키마를 고정하는 host-runnable contract test 없음(`src/core/test/test_bridge_timers.py`는 import stub 목록에만 존재). SOURCE/LOCAL 모두 미실행 — 근거 부재
- gate 변화: 없음(신규 기록). SOURCE/LOCAL HOLD, ROS-SIM N/A, ARTIFACT/DEVICE HOLD(io 이미지에 포함, Device 계획과 동일 blocker), FIELD N/A
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): park interfaces field gate and point at the CI build
- 변경: 2차 리뷰 반영. io 이미지에 실리는 패키지이므로 FIELD를 PARKED로, 다음 gate에 CI `Build (colcon)` 결과를 증거로 쓰는 경로 추가
- 증거: 미실행 — 기록 정정만
- gate 변화: FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# interfaces logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/interfaces`를 본다.

## 2026-09-25 · uncommitted · refactor(contracts): move interfaces under src/contracts (D-231)

- 변경: `src/contracts/interfaces`로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 구조 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음


## 2026-10-04 · uncommitted · interfaces: additive typed recording start options

- 변경: 기존 SetBool start/stop을 유지하고 RAW/ANNOTATED 두 값을 받는 PilotRecordingStart 서비스 정의를 추가했다. ROS 서비스는 녹화 근거만 요청하며 바퀴 제어를 하지 않는다.
- 증거: service surface 및 recorder typed option 거부·원본 보존·manifest 회귀 53 passed. 실제 rosidl 생성은 ARM64/ROS CI 빌드에서 확인한다.
- gate 변화: 없음. host 검사로 rosidl/기기 수용을 주장하지 않는다.

## 2026-10-17 · uncommitted · same-SHA MapAdoption 생성·직렬화 검증 기록

- 변경: progress의 오래된 경로/시험 기록을 실제 revision별 결과로 갱신하고 station-native-map-wire validation을 연결했다.
- 증거: 8058c3676 remote_sim exit 0, 같은 SHA interfaces 생성·prefix/IDL/header/Python/C++ include provenance 확인, Python round trips/7개 bounded metadata 및 C++ CTest 1 PASS/0 FAIL/0 SKIP. f6ae71b14 surface 6 PASS/0 SKIP/NEW 0과 최초 fixture 예상 표기 실패를 분리 기록했다.
- gate 변화: SOURCE/LOCAL GO 유지, ARTIFACT/DEVICE HOLD·FIELD PARKED 유지. native producer/CORE admission·FULL CI·ARM64/장치/현장 수용은 미확인이다.

## 2026-10-17 · uncommitted · 생성된 Python bounded string 표기 검사 수정

- 변경: Jazzy가 반환하는 generated metadata `string<64>`와 IDL 문법 `string<=64`를 혼동한 fixture의 예상값을 실제 generated 표기에 맞췄다. production IDL/rosidl 목록은 바꾸지 않았다.
- 증거: f6ae71b14 surface GREEN 6 PASS/0 SKIP/NEW 0. 별도 remote_sim은 interfaces 생성·prefix/IDL/header/Python provenance를 통과한 뒤 이 fixture 예상값에서 exit 1이었다. C++ 검사는 그 전에 멈춰 미실행이다. 실패 artifact와 exit-code 1은 회수됐다. 수정 후 compile/직렬화를 재실행한다.
- gate 변화: 없음. 전체 native adoption·운영/장치 수용은 계속 미확인이다.

## 2026-10-17 · uncommitted · 내부 MapAdoption wire 및 실제 생성 검증 경로

- 변경: 승인된 challenge-only `MapAdoption.srv`를 실제 rosidl 목록에 추가했다. 같은 SHA의 interfaces를 재생성하고 prefix/IDL/generated header/Python 경로를 확인하는 원격 검증 스크립트와 C++·Python 직렬화 fixture를 추가했다. fixture 응답은 active/adopted=false다.
- 증거: 861c33caf의 원격 RED는 기존 3 PASS/추가 3 FAIL/0 SKIP/NEW 3이다. 두 실패는 IDL 부재, 하나는 생성 목록 부재다. 새 wire의 GREEN 및 실제 compile/직렬화는 이 변경 커밋 후 실행한다.
- gate 변화: 없음. native consumer 채택·CORE admission·ARM64 배포·장치/현장 수용을 아직 입증하지 않는다.

## 2026-10-17 · uncommitted · 내부 native 지도 readback 계약 RED 준비

- 변경: D-783의 고정 challenge-only 요청과 bounded 원본 지도/native owner 응답, 실제 rosidl 등록을 검사하는 RED 3건을 추가했다. 기존 서비스는 유지한다.
- 증거: 아직 원격 실행 전이다. 새 IDL/등록 부재를 확인한 뒤 구현하며 이 surface 검사를 native 동작·compile 근거로 올리지 않는다.
- gate 변화: 없음. 외부 REST/Fleet DTO·capability 변경은 없고 내부 wire version과 실제 생성/소비 검증은 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 내부 native 지도 readback 계약 RED 준비

- 변경: D-783의 고정 challenge-only 요청과 bounded 원본 지도/native owner 응답, 실제 rosidl 등록을 검사하는 RED 3건을 추가했다. 기존 서비스는 유지한다.
- 증거: 아직 원격 실행 전이다. 새 IDL/등록 부재를 확인한 뒤 구현하며 이 surface 검사를 native 동작·compile 근거로 올리지 않는다.
- gate 변화: 없음. 외부 REST/Fleet DTO·capability 변경은 없고 내부 wire version과 실제 생성/소비 검증은 별도다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 내부 MapAdoption wire 및 실제 생성 검증 경로

- 변경: 승인된 challenge-only `MapAdoption.srv`를 실제 rosidl 목록에 추가했다. 같은 SHA의 interfaces를 재생성하고 prefix/IDL/generated header/Python 경로를 확인하는 원격 검증 스크립트와 C++·Python 직렬화 fixture를 추가했다. fixture 응답은 active/adopted=false다.
- 증거: 861c33caf의 원격 RED는 기존 3 PASS/추가 3 FAIL/0 SKIP/NEW 3이다. 두 실패는 IDL 부재, 하나는 생성 목록 부재다. 새 wire의 GREEN 및 실제 compile/직렬화는 이 변경 커밋 후 실행한다.
- gate 변화: 없음. native consumer 채택·CORE admission·ARM64 배포·장치/현장 수용을 아직 입증하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 생성된 Python bounded string 표기 검사 수정

- 변경: Jazzy가 반환하는 generated metadata `string<64>`와 IDL 문법 `string<=64`를 혼동한 fixture의 예상값을 실제 generated 표기에 맞췄다. production IDL/rosidl 목록은 바꾸지 않았다.
- 증거: f6ae71b14 surface GREEN 6 PASS/0 SKIP/NEW 0. 별도 remote_sim은 interfaces 생성·prefix/IDL/header/Python provenance를 통과한 뒤 이 fixture 예상값에서 exit 1이었다. C++ 검사는 그 전에 멈춰 미실행이다. 실패 artifact와 exit-code 1은 회수됐다. 수정 후 compile/직렬화를 재실행한다.
- gate 변화: 없음. 전체 native adoption·운영/장치 수용은 계속 미확인이다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) same-SHA MapAdoption 생성·직렬화 검증 기록

- 변경: progress의 오래된 경로/시험 기록을 실제 revision별 결과로 갱신하고 station-native-map-wire validation을 연결했다.
- 증거: 8058c3676 remote_sim exit 0, 같은 SHA interfaces 생성·prefix/IDL/header/Python/C++ include provenance 확인, Python round trips/7개 bounded metadata 및 C++ CTest 1 PASS/0 FAIL/0 SKIP. f6ae71b14 surface 6 PASS/0 SKIP/NEW 0과 최초 fixture 예상 표기 실패를 분리 기록했다.
- gate 변화: SOURCE/LOCAL GO 유지, ARTIFACT/DEVICE HOLD·FIELD PARKED 유지. native producer/CORE admission·FULL CI·ARM64/장치/현장 수용은 미확인이다.
