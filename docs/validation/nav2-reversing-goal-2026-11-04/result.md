# Nav2 후진 허용(allow_reversing) 실물 수용 — 2026-11-04

대상: `middleware/drive/planning/nav2/params/nav2_params.yaml` `FollowPath.allow_reversing` false → true (commit 3158963651)

기체: rosy-pinky-geg6 (rosy_42, release 2026.10.29-001, bench 설치 파라미터 동일값 적용)

## 절차

1. 설치 파라미터 적용 후 standalone Nav2 그래프 재기동(노드 9개 active, CORE readiness `ready`).
2. AMCL 초기위치 지정 후 **후방 15 cm 목표, 목표 yaw는 현재 유지**(xy_goal_tolerance 0.10 → 실회전 ~5–8 cm 설계와 동일).
3. 측정: CORE odom, map-pose, LiDAR ±10° 콘 최소거리(스캔 0° = 로봇 후면, D-397).

## 결과

| 측정 | 값 |
|---|---|
| 목표 결과 | `SUCCEEDED` (회전 없음) |
| odom 변위 | 0.069 m, **body-forward −0.069 m (순수 후진)** |
| map-pose 변위 | 0.082 m 후방 |
| LiDAR 후방 거리 | 0.856 → 0.778 m (**−0.078 m**, odom과 오차 9 mm) |

## 함께 확정한 사용 조건

- 목표 yaw를 `현재 yaw + π`로 주면 "뒤돌아 서기" 목표가 되어 `rotate_to_heading`이 제자리 회전을 먼저 수행한다(실측: 바퀴 3.9 cm 이동 중 LiDAR 전방거리 −0.395 m 점프 = 회전 혼입, AMCL 믿음 자세 1.28 m 점프). **후진 이동을 원하면 목표 yaw를 현재 유지**해야 한다.
- `false` 시대의 같은 목표: 제자리 회전 후 STUCK 실패(바퀴 정지, odom 0.000 m).

## 유예

- 후진 중 배터리 전압 새그·장기 내구성은 본 기록 범위 밖.
- 원래 오도측정 회전축 과측정(~2.9×)은 본 변경과 무관한 기기 결함으로 별도 유지.
