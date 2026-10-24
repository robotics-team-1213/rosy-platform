# D-866 P0: Gazebo에서 SmolVLA 정책 실행 사슬 확인 (2026-10-25)

## 주장과 한계

SmolVLA 기본 체크포인트를 D-854 정책 실행기로 돌려 SIM CORE, `SimPolicyChain`, OMX owner를 거쳐 Gazebo 팔에 보냈다. 세 실패 경우가 모두 HOLD로 끝났고, 이전 연결과 새 연결의 재접속이 모두 거부되었다. 두 회차 6번 실행이 모두 통과했다.

이 기록은 실행 계약만 확인한다. 기본 모델은 이 작업대에서 학습되지 않았다. 시험 대상은 출력을 관측값 ±0.04 rad와 관절 한계 안으로 자르고 그리퍼는 읽은 값에 고정한다(`policy_chain_vla_child.py`, D-864 §5). 작업 성공, 모델 성능, 지연 한계는 이 기록의 주장이 아니다. 지연은 GPU 단독 측정(D-866 §4)으로 따로 정한다.

## 조건

| 항목 | 값 |
|---|---|
| 커밋 | 2회차 `5dee0e795c` (1회차 `252b818d08`, 같은 시험 코드) |
| 명령 | `remote_sim.py --host ai --minutes 25 --durable cmd -- "... policy_chain_vla_gazebo.py --case <stale\|stop\|revoke>"` |
| 실행 PC | AI PC, RTX 5080 Laptop, D-867 범위 12코어·10GB |
| 환경 | `__EGL_VENDOR_LIBRARY_FILENAMES=.../10_nvidia.json`, `OMX_CELL_OVERLAY=~/rosy-test/omx-native-sim-preparation-*/install` |
| 체크포인트 | `lerobot/smolvla_base`, 파일 sha256 `b2e1a3df9c1df678cb88df85a5fee23e982953c947ac3bc9af36af8d14ece5ad`, 허브 리비전은 실행 기록 `child-ready.json`에 있다 |
| 버전 | lerobot 0.4.4, torch 2.7.1+cu128, transformers 4.57.6, `n_action_steps=1`, AMP 꺼짐 |
| 카메라 | `workcell_camera`를 복제한 top + front, 320×240 RGB, 5Hz |
| 계약 시간 | 주기 1.5s, 관측 나이 3s, 행동 나이 0.4s. 시험용 owner 관절 상태 나이 1.0s |
| 안전 값 | lease 1s, Fleet 교환 0.25s, 갱신 여유 3×0.25s. 바꾸지 않았다 |

## 결과

각 경우는 정상 3걸음 뒤 대상 동작을 한다.

| 회차 | 경우 | HOLD 이유 | Fleet 교환 중앙값/최대 | 갱신 최대(횟수) | 50ms 넘는 멈춤 | 실시간 배율 |
|---|---|---|---|---|---|---|
| 1 | stale | `policy_action_stale` | 6.1 / 156 ms | 249 ms (23) | 4회, 최대 90 ms | 0.75 |
| 1 | stop | `local_stop_closed` | 4.6 / 83 ms | 205 ms (23) | 4회, 최대 95 ms | 0.80 |
| 1 | revoke | `policy_authority_stale` | 5.9 / 59 ms | 110 ms (22) | 4회, 최대 71 ms | 0.76 |
| 2 | stale | `policy_action_stale` | 5.2 / 97 ms | 182 ms (25) | 9회, 최대 84 ms | 0.77 |
| 2 | stop | `local_stop_closed` | 5.5 / 72 ms | 174 ms (22) | 5회, 최대 64 ms | 0.74 |
| 2 | revoke | `policy_authority_stale` | 5.0 / 28 ms | 54 ms (23) | 1회, 최대 68 ms | 0.83 |

- 정상 걸음의 관측부터 제출까지는 0.12~0.16s였다(추론 약 0.13s). stale 경우는 0.5s 늦게 제출했다.
- 매 걸음에서 두 카메라 프레임의 sha256이 CORE가 잡은 원본과 같았다.
- 메모리 최대 4.2~5.2GB였다.

## 통과까지 고친 환경 사실

교훈: `docs/solutions/runtime-errors/stock-rclpy-executor-starves-sim-lease-renewal-2026-10-25.md`.

1. 실험실 PC에서 headless Gazebo의 EGL은 Mesa(CPU)로 떨어진다. NVIDIA 벤더 파일을 지정해야 한다.
2. OMX 스택은 `/opt/omx_ws`가 아니라 `~/rosy-test/omx-native-sim-preparation-*/install`에 있다.
3. 렌더 카메라 두 대는 `joint_states`를 sim 시간으로 최대 0.53s 멈춘다. 그래서 시험용 owner 관절 상태 나이를 1.0s로 둔다. owner의 검사 자체는 그대로다.
4. AI PC 디스크가 95% 차 있어 Fleet SQLite fsync가 40~55ms 걸렸고, lease POST 하나가 0.32s였다. 시험의 SQLite는 `/dev/shm`에 두고 끝나면 증거로 복사한다.
5. 기본 `MultiThreadedExecutor`가 GIL 표본의 82%를 대기 집합 순회에 썼다(`py-spy --gil`). 그 때문에 갱신 스레드가 밀려 lease가 끝났다. 제품 owner의 `OwnerMultiThreadedExecutor`로 바꾼 뒤 교환 중앙값이 21~43ms에서 5~6ms로 줄었다. GIL 전환 간격을 줄인 실험은 효과가 없어 되돌렸다.
6. owner 실행기로 바꾸자 관절 입력이 약 97Hz가 되었다. 세션의 관측 이력 64개는 약 0.66s만 담는다. 그보다 늦은 행동은 `policy_candidate_scope_or_observation`으로 거부된다. stale 경우는 이 범위 안에서 행동 나이 검사를 확인한다.

## 남은 일

- 운영 CORE(`middleware/core/gateway/core/node.py`)는 기본 `MultiThreadedExecutor`를 쓴다. lease 작업자를 같은 프로세스에 둘 때 같은 굶주림이 생길 수 있다.
- 행동 나이 한계가 관측 이력 길이(64 ÷ 관절 주기)보다 길면, 늦은 행동은 나이 검사에 닿기 전에 이력 밖 거부로 끝난다. 두 거부 모두 HOLD지만, 실물 계약 시간을 정할 때 이 관계를 같이 본다.

원시 실행 기록(시험 출력, `exchanges.json`, `renewals.json`, `stalls.json`, Fleet `server-timing.json`, 기본 실행기 `py-spy --gil` 표본)은 커밋하지 않았다. 저장소 밖 작업 공간의 `Rosy/docs/workspace-records/2026-10-25/omx-vla-p0/`에 회차·경우별로 있다.
