## D-1032 OMX 두 팔 집기 정책(`omx_two_arm_policy`) CORE 계약 정렬 — `--no-goal` 기본 경로 및 평가 시 `temporal_ensemble_coeff` 강제 덮어쓰기 제거

**Status:** Proposed (2026-11-15, Phase A·Phase B `v24-20261114` `--no-goal` 100k 검증 및 `arm_a` 실패 원인 분리 완료; 유휴 팔 자세 일치 수정 후 재검증 필요, 실물 승격 별도)

잇는 결정: [D-854](D-854-omx-policy-runner-and-action-space.md)(CORE `policy_runner` 입력·chunk 계약) · [D-969](D-969-omx-two-arm-act-from-isaac-ik-demonstrations.md)(두 팔 OMX ACT 관절+영상 입력) · [D-1015](D-1015-omx-imitation-speed-parity-temporal-ensembling-and-kinodynamic-streaming.md)(모방 속도 일치·temporal ensembling 인용) · [D-911](D-911-omx-native-reviewed-operating-envelope.md)(실물 안전·소유 경계 불변)

### Context

`tools/sim/omx_two_arm_policy_helpers.py` 기반 집기 정책 실험에서 다음 구조적 불일치와 실패가 관측되었다.

1. **과소학습 및 평가 격차:** `retrain2`(`20261114T231725-05dc639e`, 30,000 steps × batch 8, 약 3.7 epoch, loss `0.52 → 0.044 → 0.029`)의 라운드 결과에서 교란(`zero_error_deg=4.0, servo_lag=true`) 시 IK 기준선은 **50/57**(`wilson [0.768, 0.939]`)이었으나 ACT는 **2/57**(`stack/s7`, `outbound/m1`)에 그쳤다(`spoiled_runs` 30건). 교란을 제거한 실험 1(`clean-eval`, `zero_error=0`, `servo_lag=off`)에서도 **14/57**(`stack` 11/27, `outbound` 3/30)이며, `arm_b`만 14/33(`s1,s3,s4,s6,s7`, `m1`) 통과하고 `arm_a`는 0/24(`s2,s5,s8`에서 `container_to_tcp_mm` 21.8–26.6 mm)로 전패했다.
2. **평가 시 temporal ensembling 강제 덮어쓰기:** `Driver.__init__`가 학습 체크포인트 설정(`temporal_ensemble_coeff=None`)과 무관하게 `config.temporal_ensemble_coeff = .01, config.n_action_steps = 1`과 `ACTTemporalEnsembler(.01, config.chunk_size)`를 무조건 주입하고 있었다. 이는 D-1015에서 연속 스트리밍 맥락으로 인용되었으나, D-854의 CORE 실물 계약(`temporal_ensemble_coeff` 미사용)과 다르고 비정상 정지·진동·다중 모드 집기 구간에서 궤적을 평균화해 2 cm 이상 오차를 키울 수 있다.
3. **시뮬 전용 22차원 goal 벡터 의존:** `collect`/`Recorder`/`Driver.act`가 시뮬레이션 정답 상태(`observation.environment_state`, 22차원)를 필수 입력으로 묶고 있다. 실물 CORE(`policy_runner.py`, D-854·D-969)에는 해당 상태 벡터가 없으므로 현 상태의 학습 가중치는 실물로 이전할 수 없다.

### Decision

1. **평가 시 체크포인트 설정 보존 (기본 `temporal_ensemble_coeff=None`).**
   `Driver.__init__`에서 `config.temporal_ensemble_coeff = .01`, `config.n_action_steps = 1`, `ACTTemporalEnsembler(.01, ...)`의 무조건 덮어쓰기를 제거한다. 명시적 진단이나 비교 실험이 필요한 경우에만 `--ensemble-coeff` 및 `--n-action-steps` CLI 인자로 선택 적용한다(기본값 `None`, 체크포인트 설정 유지; CORE 일치 점검 시 `--n-action-steps 1` 병행 비교 가능).
2. **`--no-goal` 수집·라운드 경로 도입 (`D-854`/`D-969` 정렬).**
   `collect`와 `round`에 `--no-goal` 플래그를 추가해 `observation.environment_state(22)` 없이 `observation.state(12)` + 카메라 영상(`observation.images.*`)만으로 데이터셋을 생성·학습할 수 있게 한다. `Driver`는 로드된 정책의 `config.input_features`에 `observation.environment_state`가 포함된 경우에만 `GOAL`을 전달하므로 기존 `retrain2` 체크포인트와 `--no-goal` 체크포인트를 모두 호환 실행한다.
3. **실물 경계 및 단계별 검증.**
   - 본 변경은 `tools/sim/` 시뮬레이션 수집·평가 범위로 한정하며 `policy_runner.py`, `ALLOWED_OWNERS=("rule_based",)`, `D-793`, `D-911` 실물 실행·안전 가드 및 `D-427` 부품 소유 경계는 변경하지 않는다.
   - **Phase A (진단 완료):** 무재학습 상태에서 `retrain2`(`5cda032f57` 산출)를 `606aaa1e8e`(`main` 계통)에서 `ensemble=None`으로 평가한 결과 `n_action_steps=8`(`0/57`), `n_action_steps=1`(`0/57`), 비교군 `--ensemble-coeff 0.01 --n-action-steps 1`(`task-505`, seed 0 `0/9`) 모두 통과하지 못했다. 동일 `5cda032f57` 코드베이스에서 `ensemble`만 끈 비교(`task-515`, seed 0)도 `0/9`(vs `clean-eval` seed 0 `5/9`)였으며, `arm_a` `s2,s5,s8` 오차는 `21.8–24.8 mm → 14.2–15.8 mm`로 줄었으나 3.7-epoch 정책의 `arm_b`가 `5/6 → 0/6`으로 무너졌다. 즉 (a) 미착지 `5cda032f57`의 하강 속도/제어 변경과 `main` 사이 교차 브랜치 불일치, (b) `temporal_ensemble=.01`이 3.7-epoch 과소학습의 불안정을 가리면서 `arm_a` 정밀도를 깎던 이중 원인이 분리되었다.
   - **Phase B (`v24-20261114` 완료 · 원인 분리 완료):** 최신 `11-14` 탑뷰·`v24-docks` 기준(`feat/omx-sim-dock-v24-loop` `f9c1f9015e` + `D-1032` 패치, `--choice preset=v24-20261114 --no-goal --zero-error-deg 0 --skill grasp --batch-size 32 --steps 100000`, 라운드 `20261115T044528-b7f2ccb9`)에서 수집 570 ep(44,307 frame, `spoiled=0`)·학습(100k step, `chunk=30, n_action_steps=8, lr=1e-4`)·평가 결과 IK 기준선 **57/57**(100%, `wilson [0.937, 1.0]`), ACT(`--no-goal`, `ensemble=None`) **33/57**(57.9%, `wilson [0.45, 0.698]`)를 기록했다.
     - **`arm_b` 30/33 (90.9%):** `stack` 전 스텝 **18/18**(100%, `container_to_tcp_mm` 3.5–4.2 mm), `outbound` **12/15**(`m2,m3,m5,m9` 각 3/3 `3.0–4.4 mm`, `m1 ship-h1r0-l1`만 0/3 `16.7–18.0 mm`).
     - **`arm_a` 3/24 (12.5%):** `outbound/m0`만 **3/3**(2.7–2.9 mm) 통과했고 `s2,s5,s8`(206.7–223.8 mm)·`m4,m6,m7,m8`(83.4–269.0 mm)는 모두 실패했다.
     - **원인 검증 (`arm_a` 유휴 팔 상태 분포 불일치):** 학습 프레임 0 open-loop 추론은 12개 태스크 전부 `max_err` 0.002–0.024 rad로 정확했다. 그러나 수집(`Recorder.run_task`)은 `isolated=False`로 연속 실행해 직전 `arm_b` 스텝이 남긴 유휴 자세(`b_gripper=0.442–0.449`, `b_elbow=1.654`)가 `s2,s5,s8,m4,m6,m7,m8` 전량에 기록된 반면, 첫 스텝 `m0`와 평가(`skills.isolated` → `teacher.fresh`)는 유휴 팔이 `wait`(`b_gripper≈0.95–1.00`)로 시작한다. 스왑·개입 시험에서 평가 시 `arm_a` 입력의 `state[6:]`만 수집의 유휴 자세(`[1.595,-1.955,1.654,1.619,-1.722,0.449]`)로 치환하자 모델 가중치 변경 없이 **전체 11/19 → 17/19**(`stack 9/9` 100%, 비-`m0` `arm_a` `0/7 → 7/7`, `0.6–6.2 mm`)로 반전되었고 반대로 `m0`만 실패(90.7 mm)했다(`m1`은 유휴 `arm_a` 치환 후에도 `18.1 mm`로 남아 근접 층 `m1`/`m2` 1스텝 precision 한계).
     - **후속 조치 (적용·재검증):** `collect`가 `--skill` 수집 시 `teacher.run_task(..., isolated=True)`로 매 스텝 `fresh(here)`를 호출하도록 정렬해 유휴 팔 자세 불일치를 제거한 뒤 `v24-20261114` `--no-goal` 100k 재학습·재평가를 실행한다. 기준(`SKILL_PASS 90%`) 통과 후 본 ADR의 Accepted 전환 및 후속 도메인 무작위화·실물 이전을 검토한다.
