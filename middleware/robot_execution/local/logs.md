# execution_local logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
등록 전 이력은 `git log -- middleware/robot_execution/local`를 본다.

## 2026-10-27 · uncommitted · refactor(harness): register execution_local as a control wheel module

- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가. 동작 변경 없음.
- 증거: 원격 시험 PC에서 `middleware/robot_execution/local/test` 276 passed, 0 skipped.
- gate 변화: 신규 기록. SOURCE GO, 나머지 gate는 등록 시점에 평가하지 않아 PARKED.
- 결정: D-61, D-168
- 교훈: 없음

## 2026-11-05 · 348778e549 · fix(learning): 공용 학습 계약 wheel pin 정합

- 변경: learning contract의 정확 pin을0.1.16으로 맞췄다. 설치 검사·owner session·HOLD 동작은 변경하지 않았다.
- 증거: [검증 기록](../../../docs/validation/omx-smolvla-reviewed-cycle-2026-11-05/result.md). 이전 정확 pin과 새 wheel의 충돌은 실제 원격 venv pip check에서 재현했고 수정 후 설치·아키텍처 회귀를 확인했다. 최종 FULL 결과는 위 기록을 따른다.
- gate 변화: 없음. 기존 SOURCE GO와 나머지 PARKED를 유지한다.
- CE: 해당 없음 — 의존성 metadata와 설치 회귀가 원인·수정을 설명한다.

## 2026-11-06 · uncommitted · test(execution): 최초 lease 실패 보존과 HOST timing 진단

- 변경: main67e118e95b와 보존 BE를 정상 병합하고 deploy 기록 충돌만 양쪽 보존했다. HOST fixture는 예외 메시지·요청·응답·토큰·session 값을 출력하지 않고 숨겨진 context의 type/status, HTTP 경과·닫힘 상태, 서버 수치 timing, 공개 module hash와 storage category만 기록한다. setup의 constructor 재시도는 제거했다. fault injection은 최초 예외 객체가 그대로 전파되고 constructor·모의 acquire가 각각1회뿐임을 검사한다. 제품 policy·1초 lease·HTTP default0.2초/max0.25초·정상 renew 무재시도·HOLD/stop/goal 본문 검사는 그대로다.
- 증거: source1d3a249851의 동일 AI 순차 single-node 비교는 진단 arm(privacy 포함)2통과/env e07c71b39e34be4b, 원본 main67 arm1통과/env35327e86830df3ba였다. freeze는 모두906d7aca580f620b지만 같은 venv나 동일 부하를 뜻하지 않는다. 진단 arm은 disk에서 client HTTP 최대13.22ms·server HTTP 최대22.03ms·store wall 최대3.67ms/CPU 최대1.35ms였고, 실제 로드한 policy lease/chain 공개 source hash는 양쪽 Git source와 일치했다. main arm의 effective import/timing은 추가 계측하지 않았다. scratch policy-lease-pair/{diagnostic,main67}/run-1.txt.
- directory: source78a664bb2f는 같은 AI·W2·정본 memory history reserve1GB로 전체 local/test를 딱1회 실행해278통과·3skip·NEW/known/flaky0, env10a40e765d569d55/freeze906d7aca580f620b였다. 기존 directory의3skip 수를 유지하고 privacy·최초 실패 보존 회귀를 포함한다. scratch policy-lease-directory-once/run-1.txt. root의 고정 source 독립 검토 미해결 finding 없음.
- 한계: old032235의 최초 acquire 실패와 단독 정상 renew 실패에는 PermissionError 외의 typed context/server timing이 남지 않았다. 당시 package peak314MiB·평균0.70core, 단독 BE162MiB·0.63core, mainf4164MiB·0.83core였고 AI 입장 직전 free memory1.8/2.8GB는 부하 정황일 뿐 원인 증거가 아니다. 원래 정상 renew 실패는 이번 single-node와 directory에서 재현되지 않았으며 해결됐다고 주장하지 않는다.
- gate 변화: 소유 test/fixture와 기록만 변경했다. source별 제한된 증거를 보존하고 새 main·OMX 후속 코드는 병합하지 않았다. baseline187·승인 부모와 모든 STOP을 보존하며 land/push·새 FULL·실물·운영 서비스 변경은 수행하지 않았다.
- CE: 미해결 — 원래 정상 renew 실패의 원인은 미확정이다. 기존 stock-rclpy lesson의 client/server 비용 측정만 적용했고 ROS executor가 없는 HOST fixture에 Gazebo의 원인을 전용하지 않았다. constructor 재시도 제거의 효과와 원실패의 원인 판정은 분리한다.
