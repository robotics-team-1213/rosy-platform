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
4. **준비·프리플라이트:** 세트를 합쳐 10칸 목표 데이터셋을 만든다. 출처 폴더 이름(`arm_a`/`arm_b`)이 같아야 하며 `experiment_cuda_train.preflight_cuda()`가 비어 있지 않은 `output_dir`(`resume=False`)·`gate-receipt`·`~/rosy-jobs` GPU lock을 사전 검증한다(`run-chain-v2.sh`에서도 `mkdir -p "$W/$ARM/train"` 금지, 부모만 생성).
5. **학습:** `hold_gpu.sh 4 8`(`gpu.lock`, PC당 학습 1개) 아래 `lerobot_train` ACT: chunk 16, n_action 4(v2 기준: `ResNet18`, `dim=256`, `enc=4`·`dec=1`, `use_vae=true`, `kl_weight=10`, `cosine 20k 1e-4→1e-6`, `backbone_lr=1e-5`, batch 16, 밝기·대비 ±20%·이동 2%, 4k~5k 저장).
6. **평가·번들·고르기:**
   - 저장마다 개발 시드(`3101..3108`)로 폐루프 평가(`ladder3`), 인접 안정 구간을 고른 뒤 봉인 시드(`5301..5307`)는 단일 승자 1회만 쓴다.
   - `learning/registry/policy/sim_l1.py` `rosy.sim-l1-eval/2` 게이트는 **nominal(`n4_d0`) + delayed(`n8_d7`)** 프로파일과 **층별(`per_layer`, 0안착 층 거절)**·이웃/링크 충돌 0을 함께 검사한다.
   - 셀 반입 전 `experiment_artifact.package_cell_bundle(..., rename_views={'rs':'top'})`로 `config`/`preprocessor`/normalizer `.safetensors` 키(`rs→top`)·`device=cpu`·`UNITS.json`·`VIEW_NAMES.json`·심볼릭링크 없음을 자기검증한다.

## 함정 (실제로 겪은 것)

- **체크포인트 진동·출력dir 크래시:** 같은 판에서 인양 22/24 → 0/24 진동이 흔하므로 마지막 저장을 자동 채택하지 않는다. 체인 스크립트가 `train/` 폴더를 미리 만들면 `lerobot_train`이 `FileExistsError`로 6초 만에 죽는다(PR #491 preflight + 즉시 reaper로 차단).
- **프레임 누락·정지 화면:** LeRobot 읽기는 누락을 가린다(게이트 필수). 정지 화면 검수는 실물에만 적용(PR #420).
- **셀 CPU 추론 데드라인 불가식 (`i7-1165G7` 4C/8T):** `chunk_size=16 @ 15fps`(`1.067s`)에서 `obs_age≈0.64s`(`dropped=9`)이면 chunk 1 예산이 `<=0.400s`뿐이다. 실셀 순수 PyTorch CPU 실측 최솟값은 `threads=4` `0.4084s`(ResNet18 3뷰 `0.3512s` + 트랜스포머 `0.088s`), `threads=1/8`·`channels_last`·`bf16`·동적 `int8`은 오히려 `0.67~1.95s`로 느리므로, 로컬 CPU 단독 `<0.35s` 불가 시 ONNX/원격 추론/청크 확장 없이 `--max-obs-age-s`만 올려도 chunk 1에서 반드시 정지한다.
- **B 팔 `±180°` 손목 롤 이중 분기 평균화:** 실물 B 홈(`roll≈+45.2`)과 시뮬 wait(`roll≈-54.8`) 혼합 모델은 실프레임에서 `wrist_roll≈-12.9`(두 분기 중간)과 `shoulder_lift=-74.4`(검토 하한 `-65.2` 밖)을 내어 `dry-run` 및 live 거절된다(`input_wrist_roll`을 `-54.8`로 주면 경고 해소 확인). `h1` 실물 시연·검토 `ship-h1` library 없이 실구동 금지.
- **셀 배포 링크:** `~/rosy-test/omx-tools-current`는 `cell/adaptive-ship` 캘리브레이션이 물고 있으므로 임의로 `main`으로 바꾸지 말고 격리 링크만 쓴다. 공유 정본은 HF `robotteam/rosy-omx-data`(개인 계정 금지).
