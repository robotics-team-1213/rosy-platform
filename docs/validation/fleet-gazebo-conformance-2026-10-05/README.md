# Fleet–Gazebo 실제 통신·주행 검증 — 회차 증거 (D-426)

**Status:** T1–T6 구현·계약 완료. 실제 WSL Gazebo 회차(M01–M08 × seed 3 × 3회) 실행 대기.

**ADR:** [D-426](../../../adr/D-426-fleet-gazebo-end-to-end-conformance.md)
**계획:** [2026-10-03-fleet-gazebo-conformance.md](../../../plans/2026-10-03-fleet-gazebo-conformance.md)

## 구현 완료 조각

| Task | 내용 | 시험 |
|---|---|---|
| T1 | 실행 격리·preflight(run별 예약·manifest·READY 7탐침) | 12 계약 |
| T2 | 통신·결과 상관 probe(페어링→WELCOME→goal→CORE event→종단 투영) | 13+ 계약 |
| T3 | 독립 관측기·수치 판정(도착·정지·여유·contact·epoch) | 15 계약 |
| T4 | 구간 진입 허가·점유(FREE→RESERVED→OCCUPIED→RELEASING→FREE) | 10 계약 |
| T5 | 장애 주입 시나리오(M01–M08)·sim base watchdog(0.30 s) | 14 계약 |
| T6 | 회차 보고서 생성기(시나리오/주행 판정 분리) | 7 계약 |

## 회차 실행 절차 (WSL)

1. `python tools/validation/fleet_gazebo/run.py --robots 2 --scenario all --output-root /mnt/x/DevTemp/fleet-gazebo --world <world> --map <map> --profile <profile>` — run root·오버레이·run_spec 생성
2. WSL에서 colcon build(산출물은 `/mnt/x/DevTemp/fleet-gazebo/<run_id>/` 로)
3. `ros2 launch gz_sim gz_multi.launch.py robots:=2 core:=true run_spec:=<run_spec>`
4. M01–M08 회차 — probe(T2)·assertions(T3) 판정 → 회차별 `verdicts.json`
5. `python tools/validation/fleet_gazebo/report.py --rounds-dir <rounds> --output docs/validation/fleet-gazebo-conformance-<date>/result.md`

## 남은 것

- 실제 WSL Gazebo 회차 실행(M01–M08 × seed 3 × 3회)·원본 보존
- URDF 접촉 센서 배선 + 양성 대조(T3 계획 항목 2)
- ROS-SIM 게이트 승격 — 회차 판정 전부 PASS일 때만
