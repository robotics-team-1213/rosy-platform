# NE 링 호의 관측 없는 거리 한계 검토, 2026-10-09

**증거 등급: 기존 ROS-SIM 로그의 오프라인 분석.** 참값은 사후 평가에만 썼다. 새 제어 규칙, 장치의 허용 blind 거리, 실물 주행 합격을 만들지 않는다.

## 재현 입력

[진입 자세 재계산](../lane-pivot-pose-audit-2026-10-09/result.md)과 같은 `X:\DevTemp\d520-obs\`의 NE 기본 4회 및 참값을 보고 지시를 바꾼 비교 4회다. [thresholds.py](evidence/thresholds.py)가 첫 `lane_arc` 뒤 연속 호 주행 로그의 오돔 점 사이 거리를 합산하고, Gazebo 참값 자세의 지도 원 반지름 오차가 처음 25 mm·50 mm에 도달한 **로그 지점**을 찾는다. [thresholds.jsonl](evidence/thresholds.jsonl)에 run별 입력 SHA-256과 결과를 고정했다. 8개 로그의 해시는 원 녹화의 [checksums.sha256](../lane-arc-fit-observability-2026-10-09/evidence/checksums.sha256)과 모두 일치한다.

```text
python docs/validation/lane-arc-blind-envelope-2026-10-09/evidence/thresholds.py --centre -0.3357 0.0011 --radius 0.2514 X:/DevTemp/d520-obs/ne_01 X:/DevTemp/d520-obs/runs_ne_base3/ne_02 X:/DevTemp/d520-obs/runs_ne_base3/ne_03 X:/DevTemp/d520-obs/runs_ne_base3/ne_04 X:/DevTemp/d520-obs/ne_oracle_01 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_02 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_03 X:/DevTemp/d520-obs/runs_ne_oracle3/ne_04
```

## 결과

| NE 조건 | 첫 25 mm 도달 거리 | 첫 50 mm 도달 거리 | 호 전체 최대 `|Δr|` |
|---|---:|---:|---:|
| 기본 `turn_deg: −97.4°`, 4회 | **0.1104–0.1281 m** | **0.2927–0.3124 m** | 0.0522–0.0529 m |
| 참값 기반 비교 `turn_deg: −110.4°`, 4회 | 도달하지 않음 | 도달하지 않음 | 0.0044–0.0053 m |

기본 조건에서는 D-520의 첫 맞춤 검사 구간 0.10 m를 조금 지난 뒤 25 mm에 도달했다. 현재 `arc_blind_max_m: 1.0`은 단계 1 SIM용 전체 구간 값이고, `lane_arc_fit.py` 후보는 제어에 아직 연결되지 않았다. 따라서 **첫 확신 맞춤이 없더라도 기존 값으로 링 전체를 계속 간다**는 동작을 실물에서 안전하다고 볼 수 없다. 25 mm는 D-520이 진입 방향 오차에 배분한 여유이지 차체 경계나 정지거리의 실측값이 아니다. 첫 도달 거리도 로그 간격으로 양자화돼 실제 연속 crossing은 그보다 앞일 수 있다.

이 결과는 첫 0.10 m에서 지도 자세·바닥선 맞춤·오차 상한 중 어떤 진입 근거가 실제로 마련되는지부터 검증해야 함을 보여 준다. 근거가 없으면 허용 거리를 임의로 0.10 m로 놓지 않는다. [Fleet 계획·한쪽선 설계](../../plans/2026-10-09-fleet-plan-lane-evidence-design.md)의 차체 여유·불확실도·정지거리 계산과 D-520 계약 개정, 같은 SW·NE·lap 폐루프 SIM 재시험이 먼저다. 현재 코드는 변경하지 않았고 장치 `arc_enabled` 활성화 근거도 늘지 않았다.
