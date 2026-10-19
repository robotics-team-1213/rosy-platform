# OMX native 이송 중 배치 변화와 watchdog 관측 경계

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 source `24c09ba999`, nonce `9285d75dd798`.
[이전 배치 HOLD](../omx-native-topic-task-2026-10-17/result.md)의 후속이다.
새로 배포한 run을 한 번만 시작했다. 준비만 끝낸 이전 nonce `b20027c9485c`는 시작하지 않았다.

## 실제 실행

격리 설정과 자원 상한을 확인했고 startup READY, topic prepare PROPOSED,
admission READY를 거쳐 실제 canonical OMX owner가 작업을 실행했다.
첫 물체 목표 확인 후 두 번째 release에서 `joint_state_stale`에 의한
LOCAL_ACTION_HOLD로 끝났다. 목표 확인은 1/16이며 전체 task 성공이 아니다.

독립 pose trace는 COLLECTED, registration_failure=null, diagnostic_failure_count=0이었다.
첫 물체의 목표 확인에 사용한 관측 시각은 wall 1792234840.196, 추적 등록은
1792234840.532로 **0.336초의 관측 등록 공백**이 있다.

첫 2 mm 이동 trigger는 wall **1792234873.915626**, SIM **100.268**에서 기록됐다.
두 번째 transfer 구간은 wall 1792234856.650814부터 1792234875.062269까지이며,
release submission은 1792234875.151344다. 따라서 이 실행의 첫 기록된 움직임은
**이송 중**, release submission보다 **1.236초 앞**이다. release jaw opening이 최초
원인이었다는 가정은 이 기록과 맞지 않는다.

trigger의 pose는 (0.20767426, 0.07245411, 0.02293471) m였다. 직전 관측은 z가
0.024124 → 0.023692 → 0.023213 m로 내려갔고, 이후 z=0.02193193 m까지 내려갔다.
이 trace는 독립 pose 변화와 기록된 phase 시각의 상관관계다. 접촉한 collision/link나
Gazebo producer 시각을 확정하지 않는다. trigger 2 mm/2도는 진단 수집 기준이며
기존 goal predicate·허용 오차·HOLD 조건은 바꾸지 않았다.

## 시계 기록으로 아직 단정할 수 없는 것

후속 terminal snapshot에는 source stamp 113.560초가 검사 source_now 112.854초보다
0.706초 앞선 STAMP_REJECTED가 있었다. 검사 received_at도 112.854초였다.
intake 수락/거절 누계는 8338/117이다. 기록 당시 owner/runtime 최신 sequence는
같았으며, 더 앞선 owner 전달 지연을 이 값으로 입증할 수 없다.

중단 이벤트 시각과 진단 snapshot 사이에는 약 **1.576초** 차이가 있다. owner 관절 wall
시각도 이벤트보다 0.818초 뒤여서 이후 수신이 이미 반영됐다. 그러므로 이 최신 거절
한 건이나 누계를 앞선 HOLD의 유일 원인으로 사용하지 않는다. thread preemption과
별도 /clock 전달 지연도 현재 자료만으로 구분하지 못한다.

`458698786f`은 owner.poll의 실제 선택 분기에서 취소 전에 scalar 관측을 frozen record로
보존한다. 기존 clock provider 호출 횟수·검사 순서·한계·취소를 유지하고, 기록 생성
실패도 원래 HOLD를 막지 않는다. 독립 D-430 Safety-Review APPROVE 후 원격 owner
회귀 **75 passed**를 확인했다. `db52d3bf07`은 이 값을 현재의 비원자적 snapshot과
따로 내보내며, 정확한 command ID 일치와 잘리지 않은 ID인지 표시한다. 원격 G2
관측·추적·clock·startup 회귀는 **38 passed**, 두 묶음 모두 skip/NEW/known/flaky 0이다.
이 새 decision record는 본 실행에 없었으며 다음 실행에서 확인해야 한다.

## 정리와 증거

cleanup_verified=true, remaining_groups=[], cgroup 부재, MainPID=0 / 빈 ControlGroup,
해당 실제 budget 파일 부재를 확인했다. private 운영 scratch
`native-auto-deployment-9/fetches/20261017T110204-e82b69084b0e`에 원본과 대조표를 보존했다.

```text
archive_sha256 = d10e7967aafc4261073541a4725160b10784aed7ea8e0bae64a58b60660de2f7
extraction_map_sha256 = a17871dc04344de5242630b0c122b1b514de12e710bc956ee0b08d96ed8003af
```

새 배치의 형상 검토와 실제 재실행은 별도 후속 증거다. 전체 G2 fault matrix·실물 수용·
실제 시연 수집을 완료하지 않았으며, 적격 실제 episode는 0개이고 실제 ACT 학습은 시작하지 않았다.
