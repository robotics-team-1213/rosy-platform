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


## T6 보고서 입력 경계 (HOST)

각 verdicts.json에는 scenario_id(M01..M08), seed(0..2147483647 정수), repeat(1..3), scenario_verdict/driving_verdict(PASS/FAIL/NOT_RUN/INCONCLUSIVE), crashed/timed_out/observation_lost(명시적 boolean), source_files 배열을 기록한다. source_files 각 항목은 path와 sha256 두 필드이며 상대 path는 해당 verdicts.json 디렉터리 기준이다. 원본 파일이 없거나 digest가 다르면 수용하지 않는다. 명시되지 않은 실패 flag는 false로 추정하지 않는다.

시나리오마다 같은 고정 seed 3개 × 반복 3회인 서로 다른 9개 조합을 모두 요구한다. M01..M08 전체와 같은 seed 집합이 없으면 전체 HOLD다. 주행/시나리오 판정과 최악 회차는 계속 별도 표시한다. source_files에는 해당 회차 원본 run manifest와 관측/판정 원본을 보존 담당자가 결속해야 한다.

이 생성기는 파일 digest와 보고 입력 완결성을 확인한다. 파일 내용이 실제 ROS-SIM 실행에서 생성됐는지, 판정 단언이 물리적으로 참인지 인증하지 않는다. 합성 회귀의 GO는 보고 입력 판정이며 실제 ROS-SIM/DEVICE/FIELD 수용 증거가 아니다. 실제 Linux 회차와 독립 원본 대조는 여전히 미실행/HOLD다.
