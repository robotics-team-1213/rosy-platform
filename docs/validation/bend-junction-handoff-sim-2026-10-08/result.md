# 굽이→교차로 넘겨주기 SIM (모델 PC), 2026-10-08

증거 등급: **ROS-SIM (폐루프, 한 대) + 실제 Fleet trip 루프**. 장치·현장 수용이 아니다. Gazebo·ROS는 모델 PC(OMEN)에서만 돌렸다.
실물 로봇은 건드리지 않았다.

대상: `fix/bend-junction-handoff` `7cb2d775a`(main `8615e2980` 병합 위, 넘겨주기 + 리뷰 반영). 하네스는
`docs/validation/lane-trip-lap-sim-2026-10-08/evidence`의 lap 하네스를 그대로 쓰고, 격리만 바꿨다: 작업공간
`~/rosy_handoff_ws`, ROS 도메인 89, `GZ_PARTITION rosy_handoff`, CORE 포트 8288, Fleet 8289, 실행 폴더 `handoff`, world 파일
`handoff_fleet_real.world`(`evidence/handoff_run.sh`, `handoff_batch.sh`). 설정은 lap SIM과 같다(출하 기본, `bridge_enabled`
끔, D-520 `arc_enabled` 끔). 다른 세션 프로세스는 건드리지 않았다.

## 결과 (12회, 서쪽 길 출발 → NW, 계획 SW `right` → ring)

| 구간 | lap SIM 전(`caa74a53c`, 20회) | 이 브랜치 (12회) |
|---|---|---|
| 서→남 모서리 통과 | 16/20 | 11/12 (lap_11: 모서리 출구 원인 C) |
| 굽이 목격을 교차로로 넘김(`B_SW` → `waiting`) | — | 10/11 |
| SW 회전 시작 (`turning`) | 3/16 | **10/11** |
| SW 회전 끝 (SW 지시가 `reacquiring` → `idle`, 다음 구간) | 0/16 | **10/11** |
| trip 완료 (`arrived`) | 0/20 | **0/12** |

- 원인 A(역주행)·B(`approaching` 중 다음 지시)·D(`waiting` 굽이 미완료)로 끝난 run은 0이다.
- 넘겨주지 못한 1회(lap_03): 굽이 동안 keeper가 교차로를 한 번도 내지 않았다(keep 기록에 `junction_*` 없음). 굽이가
  `idle`로 끝나고 SW `right`가 `armed`인 채 keeper가 왼쪽으로 꺾어(yaw 0.98→1.31 rad) `flipping` → 후진 → `stall`로 섰다.
  이 경우는 넘겨주기로 막을 수 없고 별도 브랜치 `fix/junction-corner-hold`(기대 창 안의 keeper 모서리 회전은 HOLD)가 다룬다.
- SW 회전을 끝낸 10회는 모두 회전교차로 둘레(ring_s 8, ring_e 2)에서 섰다: `pose` 4, `junction` 3, `junction_unexpected` 2,
  `stall` 1. 회전 뒤 둘레 곡선에서 keeper가 차선을 잃고(`no_boundary` → D-407 후진) 그 뒤 감지가 창 밖이거나 차로 밖으로
  나갔다. 이것은 D-520 호 주행(`arc_enabled`, 출하 기본 끔)의 몫이고 이 브랜치 범위 밖이다.

`evidence/summary_batch_1.json`(`handoff_summary.py`), `analysis_batch_1.json`(lap `lap_analyze.py`), `sends_batch_1.jsonl`.
원시 기록은 모델 PC `~/rosy_handoff_ws/runs`.

## 한계

한 대, 한 지도, 한 출발. Fleet 지도 자세는 Gazebo 참값. 호스트 SIM은 DEVICE가 아니다.
