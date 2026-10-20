# Pinky drivable v2 시뮬레이션 재점검

2026-10-19 KST. 제품 소스·설정 수정 없이 최신 워크트리와 원본 실행 기록을 확인하고 Gazebo 재실행을 요청했다.

## 정정

**카메라 기반 drivable v2로 Gazebo 코스를 돌아 도착한 기록이 있다.** 앞선 main 중심 조사에서 최신 워크트리와 외부 scratch를 누락했다. 대체 인식의 15바퀴 기록과 별개다.

다만 기록의 “r51a·r51b 모두 arrived”는 Fleet 이벤트에 대한 설명이다. 원본 시험 결과는 r51a PASS, r51b FAIL이다. 두 실행을 모두 최종 수용 통과로 계산하면 안 된다.

## 확인한 버전과 모델

- main 조사 시점 HEAD: commit `bc2239c2f33a78f2bdb76a475015302a0ea01b52`.
- 최신 관련 워크트리: `D:/Dev/Robot/Rosy/rosy-platform/.worktrees/v2-timing`, 브랜치 `land/v2-lap-rev8`.
- 새 실행에 고정한 HEAD: commit `ff8eca4d9b4adcecaccdabf7b9e3886c4eaca789`.
- 완주 수정 집계 커밋: commit `39d2ffae42f0ab598b9ab07ac7f10acd83f69856`.
- r51a·r51b 원본 실행 소스: `91f14c997f` (`run.txt`의 remote-sim 실행 경로).
- 실제 인식 revision: `lane-seg-20261010-451f0f85`.
- 현재 AI PC ONNX SHA-256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`. 원격 manifest의 hash와 일치했다. 이전 실행의 모델은 당시 관측에 기록된 revision으로 대조했으며 당시 파일 바이트를 새로 검증한 것은 아니다.

최신 수정에는 중앙으로 복귀한 뒤 회전하는 조향, 횡단보도 관측 축 재설정·지도 벽 처리, 무시된 짧은 extend에서도 경로 안내 유지, SIM 안내 수명·실행 시간 조정이 포함된다. 이 작업은 인식 모델을 이용한 주행 연결·제어 수정이며 강화학습의 추가 효과 검증과는 구분한다.

## r51 원본 재계산

| 항목 | r51a / 모델 PC | r51b / AI PC |
|---|---:|---:|
| Fleet 상태 | started → running → arrived | started → running → arrived |
| 시험 최종 판정 | PASS | FAIL |
| 종료 정착 후 목표 거리 | 0.108 m | 0.156 m |
| 시험 허용 목표 거리 | 0.15 m | 0.15 m |
| 반대편 경유점 최근접 거리 | 0.040 m | 0.029 m |
| 샘플 경로 누적 이동 재계산 | 6.739 m | 6.812 m |
| 첫 비영 명령부터 마지막 비영 명령까지 keep_debug 인식 | learned_drivable 1,499건 | learned_drivable 1,478건 |
| 위 구간 대체 인식 기록 | 0건 | 0건 |
| 마지막 기록 명령·odom 선속도 | 0 / 0 m/s | 0.04 / 약 0.04 m/s |
| 종료 후 소유 잔존 프로세스 | 없음 | 없음 |

`result.json`의 `moved_m`는 이 한 바퀴 시험에서 시작점과 정착점 사이 거리다. 전체 주행 거리를 뜻하지 않는다. 위 누적 이동은 보존된 샘플 path의 구간 거리를 합한 근사치이며 연속 궤적의 정확한 길이가 아니다.

두 실행의 전체 keep_debug에는 시작 준비 중 denoise_fallback이 각각 1건·2건 있다. 첫 비영 명령보다 각각 13.46초, 20.201/19.996초 앞이다. 따라서 보존된 실제 주행 시간 구간에서는 대체 인식 사용을 발견하지 못했다. 모든 물리 tick의 인식을 측정한 수치로 확대하지 않는다.

두 실행 모두 횡단보도 looking 진입·해제 로그가 각각 두 쌍 있다. r51b는 Fleet arrived에도 최종 거리 기준을 넘었고 기록 끝에서 계속 이동 중이었다. r51a의 완주·정지는 확인되지만 r51b의 정확한 도착·정지 수용은 미완료다.

공통 실행 조건: GPU 렌더링, `--learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return`. 차선 복귀 검사는 껐고 횡단보도 검사는 유지했다. 전체 기능이 켜진 운용 조건의 수용으로 확대하지 않는다.

원본 경로:

- `C:/Users/SERIGGG/AppData/Local/Temp/claude/d--Dev-Robot/6ffbc561-3530-46d4-bbef-14d2be577c5b/scratchpad/lap-runs/r51a/out/trips/`
- 위와 같은 상위 경로의 `r51b/out/trips/`
- 각 경로의 `result.json`, `observations.jsonl`, `launch.log`, 상위 `run.txt`.
- 집계 문서: `Rosy/rosy-platform/.worktrees/v2-timing/docs/logs.md` 9210행. 원본 결과의 차이를 위 표에 반영했다.

## 이번 재실행

AI PC에 승인된 `tools/remote/remote_sim.py`로 새 빌드·Gazebo 실행을 요청했다. 현장 PC와 실물 장치에는 실행하지 않았다. 최신 워크트리 HEAD를 고정하고 r51과 같은 모델 pointer·실행 인자를 사용한다. 이후 main 병합이 포함된 소스이므로 r51과 바이트가 같은 재현 실행은 아니다.

```powershell
python tools/remote/remote_sim.py --host ai --sha commit ff8eca4d9b4adcecaccdabf7b9e3886c4eaca789 --minutes 60 --log-dir C:/DevTemp/pinky-drivable-v2-recheck-20261019/run1 fleet_trips -- --render gpu --learned-lane-pointer /home/ai/rosy-test/v2-sim-lap/model-pointer.txt --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return
```

실행 식별자: `sim-ff8eca4d9b-043ecd`.

**이번 최신 워크트리 실행은 FAIL이다.** 약 523.5초 뒤 `started → running → stopped`, 사유 `stall`로 끝났다. 위치 추정은 끝까지 LOCALIZED였다. 서쪽 횡단보도에서 looking 진입·해제 후 통과했고, 하단 진입로 `ring_s`에서 진행이 멈췄다. Fleet의 기록 진행은 6.683 m, 샘플 path 누적 이동은 약 6.216 m, 반대편 경유점 거리는 0.032 m였다. Fleet의 경로 투영 진행과 샘플 실이동 합은 다른 값이다.

정체 당시 위치는 대략 `(-0.188, -0.189) m`. 마지막 50초의 최종 명령은 선속도 0, 각속도 범위 -0.6~+0.6 rad/s였다. 관측 전략은 `drivable_pivot_right`, `drivable_off_line_left`, `drivable_pivot_left` 사이를 오갔다. CORE는 TRACKING이면서 선속도가 0이었고 기록된 body gap은 약 0.34–0.35 m로 stop gap 0.02 m보다 컸다. 따라서 보존된 기록은 **전진 없이 조향·제자리 회전을 반복하다 진행 정체로 종료된 현상**을 보여 준다. 마지막 한 프레임만으로 모델·영역 선택·경로 안내·명령 집행 가운데 단일 근본 원인을 확정하지 않았다.

첫 비영 명령부터 마지막 비영 명령까지 keep_debug 출처는 `learned_drivable` 1,465건, `denoise_fallback` 1건이었다. 모델 revision은 기록된 경우 같은 `lane-seg-20261010-451f0f85`였고 원격 모델 hash도 실행 전후 같았다. 이번 실행을 fallback 0건의 순수 인식 통과로 계산하지 않는다.

종료 시 CORE OFF·lease released, 마지막 cmd_vel과 odom 선·각속도 0, `left_running=[]`를 확인했다. 이 결과는 전체 코스 실패이며 성공한 부분 구간만으로 완주를 대신하지 않는다.

결과 위치: `C:/DevTemp/pinky-drivable-v2-recheck-20261019/run1/out/trips/`의 `result.json`, `observations.jsonl`, `launch.log`, `api-log.jsonl`. 실행 로그는 상위 `run.txt`다.

현재 판단: **카메라 drivable v2의 Gazebo 완주·정지 성공 기록은 실제로 있다. 그러나 최신 병합 워크트리에서 이번에 재현한 한 번의 실행은 실패했으므로, 반복 완주가 안정적으로 확보됐다고 보고할 수는 없다.** 이 한 번의 실패만으로 특정 새 커밋의 회귀나 성공률을 확정하지 않는다. 다음 원인 비교는 성공 소스 `91f14c997f`와 현재 소스를 동일 초기 상태로 반복하고 `ring_s`의 영역·경로 안내·조향·실제 명령을 같은 시각으로 대조하는 것이다.

## 남은 범위

Gazebo 카메라 주행 완주, Isaac 카메라 주행, 강화학습의 기준선 대비 개선, 실물 적용은 별도다. 이번 조사는 Gazebo의 기존 완주 근거를 정정하고 최신 워크트리에서 재확인하는 범위다. 재학습·배포·main 착지·push·실물 주행은 수행하지 않았다.

## Pinky 실행 경로에 반영됐는가

**이번에 시험한 시뮬레이션 Pinky에는 반영됐다.** 원격 runner가 지정한 소스를 빌드했고 `--learned-lane-pointer`와 `--learned-paint-target drivable`을 launch로 전달했다. 실제 관측의 `paint_source_used=learned_drivable`, `paint_model_revision=lane-seg-20261010-451f0f85`도 대조했다. 따라서 최신 제어 코드와 모델이 연결되지 않은 상태의 시험으로 해석하지 않는다.

여기서 적용된 것은 인식 모델과 기존 Drive의 제어 수정이다. 별도의 강화학습 정책을 승격해 적재한 시험은 아니다.

실물은 설치 버전과 설정을 별도로 확인해야 한다. 저장소의 `line_observer_node.py`는 `learned_paint_target` 기본값이 `lane_marking`이다. `host_lane_perception.py`의 learned 선택은 `paint_source`, model pointer, 추론 주기·스레드·motion compensation을 설정하지만 `learned_paint_target`을 지정하지 않는다. 따라서 일반 learned 선택만으로 drivable v2 사용을 보장하지 않는다. 기존 `line_observer_overrides.py apply --paint-target drivable`가 명시적인 선택 경로다. 설치본이 이 옵션과 관련 최신 제어 계약을 지원하는지도 확인해야 한다.

실물 테스트 준비에 필요한 최소 묶음은 고정 모델/hash, 일치하는 Perception·Drive·CORE·Fleet 코드, `paint_source=learned`와 `learned_paint_target=drivable`, 실물 카메라 보정, 실제 관측에서의 모델 소비 확인이다. SIM의 정확한 pose, 안내 수명 3초, 지도 벽 처리와 검사 생략 설정은 실물 설정으로 그대로 옮기지 않는다.

이 추가 확인은 소스 검토다. 이번 대화에서 실물 장치 접속·설정 변경·재시작·운동 명령은 실행하지 않았다.
