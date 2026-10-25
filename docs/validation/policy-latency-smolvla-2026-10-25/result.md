# SmolVLA 추론 지연 재측정 — 반정밀도, GPU 연산 단독 (D-864 구현 순서 2, 3차)

**날짜:** 2026-10-25 · **위치:** AI PC (RTX 5080 Laptop 16GB) · **이전 기록:** [2차](../policy-latency-smolvla-2026-10-24b/result.md)
**판정:** autocast 반정밀도는 빨라지지 않는다. 추론 p50이 fp32 95ms에서 106ms로 늘었다. 종단 p99는 두 방식 모두 약 181ms다. 한 걸음씩 동기 추론으로는 10Hz가 안 된다는 결론과 3b(목표 묶음을 궤적 하나로) 필요성은 그대로다.

## 조건

- 커밋 `4e096cc8c2`(`feat/policy-bench-amp`)의 `policy_runner.py`. `--amp`는 체크포인트가 `use_amp: false`여도 CUDA에서 `torch.autocast`를 켠다.
- 명령: `remote_sim.py --host ai cmd -- "python -m rosy.integrations.robots.omx.policy_runner <smolvla_base> --joints joint1..joint5 gripper_joint_1 --camera camera1=480x640 --camera camera2=480x640 --unit ros_joint_rad --task 'pick the box' [--amp]"`, 예열 50, 측정 1000걸음, fp32 → amp → fp32 순서.
- 체크포인트 파일 sha256 `b2e1a3df9c1df678cb88df85a5fee23e982953c947ac3bc9af36af8d14ece5ad`, lerobot 0.4.4, torch 2.7.1+cu128, `n_action_steps=1`(저장값 50).
- GPU: 측정 앞뒤 사용률 0~4%. 다른 사용자 프로세스가 메모리 약 10GB를 잡고 있었지만 연산은 쓰지 않았다. 이 PC에서 Gazebo 등 내 다른 작업은 같이 돌리지 않았다.
- CPU: 부하 평균이 시작 2.9, 끝 7.4로 다른 사용자 작업과 함께 썼다. 전처리 꼬리(p99 43~70ms)는 이 영향으로 본다.

## 결과 (ms, p50 / p99 / 최대)

| 실행 | 전처리 | 추론 | 종단 |
|---|---|---|---|
| fp32 | 1.9 / 67.7 / 106.3 | 94.6 / 141.1 / 146.7 | 97.1 / 182.4 / 224.2 |
| amp | 1.8 / 42.7 / 97.6 | 106.3 / 158.2 / 165.3 | 108.5 / 180.6 / 208.3 |
| fp32 (반복) | 2.3 / 69.7 / 100.7 | 95.7 / 140.9 / 145.0 | 118.7 / 182.1 / 225.2 |

- 반복한 fp32는 추론 p50이 첫 fp32와 1ms 안이라 측정이 안정적이다. amp의 추론 느림은 두 fp32 사이에서 재현된 차이다.
- SIM CORE를 거친 종단은 D-866 P0 기록([omx-vla-policy-chain-2026-10-25](../omx-vla-policy-chain-2026-10-25/result.md))에 있다. 320×240 두 대, fp32에서 관측부터 제출까지 0.12~0.16s였다.
- 원시 보고서는 저장소 밖 `Rosy/docs/workspace-records/2026-10-25/policy-latency/`에 있다. sha256: fp32 `8fe2633183988b731cfb7b29116c4a7dcf306ab5c631bd44a573e8dc262b4144`, amp `769917f9ccaf72124645f0c886c03f107042a53596c62f428dfa47eb0f0f7a10`, fp32 반복 `41d03eb45f526365083a0dde4438215f8099041cf4cad55030fea009edaa802b`. 체크포인트의 로컬 캐시 경로가 들어 있어 커밋하지 않았다.

## 함께 확인한 것

- 같은 날 단일 카메라 Gazebo 회귀(`policy_chain_gazebo.py`)를 이 측정과 겹쳐 돌렸을 때 `policy_observation_stale`로 거부되었다. 단독으로 다시 돌리자 `OMX_POLICY_CHAIN_GAZEBO_PASS`와 `EXIT_OK`로 통과했다. D-866의 "GPU 측정과 시뮬레이션은 단독으로" 규칙을 어긴 실행이었고, 그 실행 결과는 쓰지 않는다.

## 확인하지 못한 것

- 가중치를 bf16/fp16으로 바꿔 올리는 방식(autocast가 아닌 변환), CUDA graph·컴파일, 학습한 체크포인트.
- CPU 단독 조건. 이 PC의 다른 사용자 작업은 멈추지 않았다.
