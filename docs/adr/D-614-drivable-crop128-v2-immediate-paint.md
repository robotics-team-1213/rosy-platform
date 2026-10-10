## D-614 crop128 v2를 로봇의 drivable paint 모델로 바로 적용한다

**Status:** Accepted (2026-10-10, 사용자 결정: 새 모델을 ADR로 정하고 바로 적용). D-599의 모델 선택을 이 버전으로 갱신한다.

### Context

- 모델 PC의 `~/rosy-ml/candidates/drivable-v13-crop128-20261010-v2`는 전달본 64개 파일의 `SHA256SUMS` 검사를 통과했다. 원본 `model/model.onnx` SHA-256은 `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`, revision은 `v13-drivable-20261010-451f0f85`다.
- 팀 README는 사람 검수 2,769장 중 추가한 어려운 장면의 test 81장에서 선 밖 바닥 오검이 기존 13.9%에서 1.7%로 감소했다고 보고한다. 이는 팀 평가 기록이며 ROSY의 독립 재생·SIM·실물 수용 증거는 아니다. `camera_provenance`는 `provisional`이다.
- 9dfk와 8kcn의 paint 포인터는 모두 이전 `lane-seg-20261010-71edcb6d`를 가리킨다. 두 로봇의 설치 릴리스는 `input.crop`을 읽는다. 원본 매니페스트에는 로더가 요구하는 `camera_profile_revision`이 없고, D-554의 `v13-drivable` 부모·라벨 계보 조건도 충족하지 않는다.

### Decision

1. **새 주행 시험 모델은 v2로 한다.** ONNX 바이트는 바꾸지 않고 `lane-seg-20261010-451f0f85`라는 별도 로봇 시험 revision으로 포장한다. 매니페스트에 `camera_profile_revision: unknown-provisional`과 원본 revision·SHA 및 D-614 시험 범위를 적는다. `input.crop`은 프레임 320×240의 112..239행, 모델 입력 `[1,3,128,320]`을 유지한다. 이름 변경은 D-554 계보를 충족했다는 주장이 아니다.
2. **적용은 로봇별 paint 포인터 교체다.** 현재 포인터·설정·서비스·모드·E-Stop을 먼저 읽는다. 로봇이 정지해 있고 진행 중인 주행·미션이 없을 때만 새 폴더를 해시 검증해 설치하고, 이전 포인터를 `paint.previous`에 보존한 뒤 원자적으로 `paint`를 전환한다. 카메라가 새 revision을 읽었다는 로그와 상태를 확인한다. 오류 시 이전 포인터로 되돌리고 다시 읽는다. 포인터 변경은 주행 명령이나 실물 성공을 뜻하지 않는다.
3. **범위는 9dfk와 8kcn의 현재 paint 사용 경로다.** 로봇을 움직이거나 E-Stop을 해제하지 않는다. CORE의 최종 `/cmd_vel`, RobotBody·IR·watchdog·Fleet 권한은 그대로다. 기존 `shadow`와 `active` 포인터는 건드리지 않는다.
4. **운영 승격은 별개다.** D-554 intake나 `deliver.py` 통과를 가장하지 않는다. 팀 test 수치와 패키지 해시만으로 연속 주행을 수용하지 않는다. D-378의 재생·그림자·누르는 동안 단계, D-475 조향 오차, Pi 지연 및 `paint_source_used`/`paint_model_revision` 비율을 각각 확인한다. 실패하면 `paint.previous`로 복귀한다.

### Alternatives

- **기존 모델 유지:** 사용자 요청과 추가 검수 어려운 장면의 개선 목적을 충족하지 않는다.
- **D-554 intake 규칙을 넓혀 즉시 운영 승인:** 사람 검수 원본 자료와 부모 규칙의 독립 검증이 없어 이번 현장 시험과 분리한다.

### Verification

모델 PC 후보 해시 → 로봇 설치본 해시·매니페스트 로딩 → 포인터·카메라 새 revision 읽기 → ROSY 재생/SIM → 실물 제한 시험을 별개 증거로 기록한다. 하나라도 확인되지 않으면 그 단계는 HOLD다.

### 후속 결정 — 두 로봇의 shadow는 원본 v1

사용자가 2026-10-10에 두 로봇 모두 `~/Desktop/drivable-v13-crop128-20261010` 원본 v1을 shadow로 지정했다. 위 3항의 "shadow는 건드리지 않는다"는 최초 paint 적용에만 해당한다. v1 ONNX SHA-256 `ede0ae96327c22f5da61dca40a75ceb2f011f163bd2fa2f3e27c1558a988d39b`를 보존한다. 원본 `v13-drivable` 매니페스트는 D-554 부모 계보 검사에서 거절되므로, 이를 통과했다고 가장하지 않고 `lane-seg-20261010-ede0ae96` 시험 별칭으로 포장한다. 설치 로더가 요구하는 `camera_profile_revision`과 crop 형식만 보충하고 원본 revision·SHA를 notes에 남긴다. 정지·차선추종 OFF·미션 없음 상태에서 기존 shadow를 `shadow.previous`에 보존하고 두 로봇의 shadow를 이 v1 시험 패키지로 바꾼다. paint는 v2로 유지한다. v1도 D-554 intake 통과본이나 운영 승인으로 취급하지 않는다. shadow가 관측 전용임을 확인하고 새 revision 읽기·해시를 기록한다. 실패하면 로봇별 `shadow.previous`로 복귀한다.

**Related:** [D-378](D-378-real-drive-errors-and-autonomy-gates.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-599](D-599-drivable-model-team-crop128.md), [D-597](D-597-drivable-keep-steering-source.md).
