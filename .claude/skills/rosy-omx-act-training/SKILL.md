---
name: rosy-omx-act-training
description: Use when training, re-training, choosing, or debugging the OMX arm A/B ACT policies (LeRobot 0.4.4, top/side/wrist cameras, 10-slot goal) on the AI PC and model PC — collecting MuJoCo teacher data, mixing real Purple-SY demonstrations, gating datasets, running hold_gpu training chains, picking a checkpoint, or when success jumps between checkpoints, a training script dies at start, GPUs sit idle, or video frames go missing.
---

# OMX A·B ACT 학습

정책 입력은 카메라 3대(top=D435, side, wrist, D-1065)·관절 6·목표 one-hot 10칸(`observation.environment_state`, 인덱스 = 열×3+층, 9 = tray)이다. 판정·기록 정본은 작업 기록과 Confluence 36503658이고, 이 카드는 순서와 함정만 둔다.

## 순서

1. **수집(시뮬):** MuJoCo 교사(`tools/sim/omx_two_arm_teacher.py`), 6색 무작위·점유 독립·`pose_random=True`. 학습 중인 PC에서 3병렬 수집하면 영상 프레임이 빠진다(11-21 96개 중 40개). 2병렬·`nice`로 돌리고 반드시 3단계 게이트를 통과시킨다.
2. **실물 변환:** `use_degrees=False` 원값(−100~100, 그리퍼 0~100)을 `arm_status_bridge.to_radians`·`cell_act_inputs.sim_gripper`로 시뮬 단위로, 30 fps는 짝수 프레임만. 팔별 `held_30mm`(A 53.83, B 53.38)·`gap_mm_per_unit` 5.0. 실물 B는 손목 롤이 시뮬과 약 π 다르다. 세션 하나는 학습에서 빼 재생 시험용으로 둔다(B S06, A S03).
3. **반입 게이트:** `learning/curation/omx/data_gate.py gate <set> --arm --source kind=sim|real,layout=random|fixed [--legacy rs=top]` → `check_receipt`. 고정 배치 시연은 무작위 학습 세트에 넣지 않는다(B가 전 체크포인트 인양 0이 됐다).
4. **준비:** 세트를 합쳐 10칸 목표 데이터셋을 만든다. 출처 폴더 이름(`arm_a`/`arm_b`)이 같아야 한다.
5. **학습:** `hold_gpu.sh 4 8`(`gpu.lock`, PC당 학습 1개) 아래 `lerobot_train` ACT: chunk 16, n_action 4, dim 256, enc 2·dec 1, VAE 끔, lr 1e-4·backbone 3e-5, 배치 4, 증강(밝기·대비 ±20%, 이동 2%). 저장 5k 이하 간격.
6. **고르기:** 저장마다 같은 개발 시드(3101~3108)로 폐루프 평가(ladder3), 인접 안정 구간을 고른 뒤 봉인 시드(5301~5307)는 한 번만. 실물 후보는 학습에서 뺀 실물 세션 재생 오차로도 본다.

## 함정 (11-20~21 실제로 겪은 것)

- **체크포인트 진동:** 같은 판에서 인양 22/24 → 0/24, 75k 최종이 0인 판이 많다. 손실은 매끄럽고 오프라인 재생 오차도 비슷해 학습 발산이 아니라 폐루프 오차 누적(복귀 시연 없음)이 유력하다. 마지막 저장을 자동 채택하지 않는다. 근본 처방(교사 라벨 DAgger·노이즈 주입 수집)은 별도 검증 뒤.
- **스크립트가 시작하자마자 죽음:** `set -u`에서 변수 하나(`py`)가 빠져 두 PC가 2.5 시간 놀았다. 체인을 띄운 뒤 첫 스텝 로그와 `nvidia-smi`를 꼭 본다.
- **프레임 누락은 읽기에서 안 보인다:** LeRobot 읽기는 가장 가까운 프레임을 돌려준다. 게이트(디코드 프레임 수 = 행 수)로만 잡힌다.
- **시뮬 카메라 정지 화면:** 고정 카메라는 움직임이 없으면 같은 프레임을 렌더한다. 정지 검수는 실물에만(PR #420).
- **재생 도구의 목표:** 실물 재생 스크립트는 목표를 tray(9)로 넣는다. 시뮬 세트 재생에는 과제 문구에서 목표를 읽게 고친 뒤 쓴다.
- **PC 간 복사:** 노트북을 거치면 0.5 MB/s, PC끼리 직접 ssh면 24 MB/s. 받는 쪽은 해시 대조 뒤 표식 파일로 학습 시작을 막는다. 공유 정본은 HF `robotteam/rosy-omx-data`(개인 계정 금지).
- **셀 실행:** 셀 CPU 추론 약 0.4 s라 n_action 8 + 비동기 선계산. 팔 동작은 cell-job-api로만.
