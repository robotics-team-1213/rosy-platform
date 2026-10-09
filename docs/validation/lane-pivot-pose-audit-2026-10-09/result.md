# 링 진입 pivot 자세 오차 재계산, 2026-10-09

**증거 등급: 기존 ROS-SIM 원시 로그의 오프라인 재계산.** 새 폐루프 주행, 실물 위치 정합 또는 주행 승인이 아니다.

## 입력과 재현

- 입력은 [D-520 관측성 실험](../lane-arc-fit-observability-2026-10-09/result.md)의 모델 PC 녹화와 실험실 `X:\DevTemp\d520-obs\` 복사본이다. 녹화 실행 코드는 당시 `a8185d3f93e276164b4a2b9c1a83e5221cd2f817`이었다. 세 녹화의 `frames.npz`·`log.jsonl` 해시는 앞 기록의 [checksums.sha256](../lane-arc-fit-observability-2026-10-09/evidence/checksums.sha256)과 일치한다.
- [audit.py](evidence/audit.py)는 각 run의 마지막 `junction_turning`과 첫 `lane_arc` 로그를 찾는다. Gazebo 참값 자세에서 지도 원 `(−0.3357, 0.0011)`, 반지름 `0.2514 m`의 첫 접선을 계산하고, 같은 로그의 오돔과 비교한다. 각 입력 로그와 녹화의 SHA-256을 [pivot_metrics.jsonl](evidence/pivot_metrics.jsonl)에 기록한다.
- 재현 명령은 아래와 같다. 출력은 run당 JSON 한 줄이며, 실물 로봇이나 CORE 명령을 호출하지 않는다.

```text
python docs/validation/lane-pivot-pose-audit-2026-10-09/evidence/audit.py --centre -0.3357 0.0011 --radius 0.2514 X:/DevTemp/d520-obs/lap_01 X:/DevTemp/d520-obs/ne_01 X:/DevTemp/d520-obs/runs_ne_base3/ne_02 X:/DevTemp/d520-obs/runs_ne_base3/ne_03 X:/DevTemp/d520-obs/runs_ne_base3/ne_04 X:/DevTemp/d520-obs/ne_oracle_01 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_02 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_03 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_04
```

## 관측

| 첫 호 | run 수 | Fleet `turn_deg` | 첫 `lane_arc` 실제 방향 − 참값 지도 접선 | 첫 호 위치의 오돔 − 참값 |
|---|---:|---:|---:|---:|
| SW 기본 | 1 | −104.7° | −0.279° | 0 mm, 0° |
| NE 기본 | 4 | −97.4° | **+15.497…+16.273°** | 전체 중 최대 1.657 mm, 0.096° |
| NE 참값을 보고 바꾼 비교 | 4 | −110.4° | **+2.905…+3.357°** | 전체 중 최대 1.093 mm, 0.063° |

기본과 비교의 지시 차이 13°에 대해 관측 방향 오차는 약 12.5–13.4° 줄었다. 이 기록에서는 오돔 드리프트보다 **진입 목표 방향과 실제 지도 접선의 불일치**가 우선 설명이다. 지시가 바뀌면 이후 경로도 바뀌므로 단일 변수의 수학적 증명은 아니다. −13°는 참값을 보고 고른 비교값이며 제품 설정이나 Fleet 지도 보정값이 아니다.

세 녹화에서 첫 호 시작 로그에 가장 가까운 영상 프레임은 −50, +57, −61 ms였다. 그 프레임의 영상 시각과 저장된 오돔 시각 차이는 23, 1, 20 ms다. 이는 샘플 간격 확인일 뿐 **같은 시각의 Fleet 지도 자세**나 바닥선 정체·맞춤 오차의 증거가 아니다. 첫 카메라 맞춤 후보의 수치와 한계는 앞 [관측성 실험](../lane-arc-fit-observability-2026-10-09/result.md)에 있다.

## 다음 판별 지점

1. pivot에서 Fleet 지도 자세, CORE 오돔, 독립 Rosy Cam 또는 LiDAR 벽 자세를 같은 `map_id`·시각·TF epoch로 기록하고 각자의 방향·옆 위치 불확실도와 지연을 측정한다. 현재 9개 로그에는 그 지도 자세와 공분산이 없어 제품의 보정 상한을 계산할 수 없다.
2. 그 상한으로 [Fleet 계획·한쪽선 설계](../../plans/2026-10-09-fleet-plan-lane-evidence-design.md)의 진입·blind 거리 문을 계산한다. 바닥 테이프/벽 식별과 카메라 외부 보정이 없으면 한쪽선 맞춤을 주행 보정에 쓰지 않는다.
3. 같은 SW·NE·한 바퀴 시작에서 새 게이트를 폐루프 SIM으로 비교한다. 독립 참값 `|Δr|`, HOLD, 벽·spoke 오추종, 도착률을 모두 기록한다. 그 전에는 현재 D-520 단계 2를 실제 구동에 연결하지 않는다.
