# Pinky 정렬 상태 수명 수정과 후속 반복 — HOLD

2026-10-19 KST. [앞선 관측 정렬 기록](../pinky-corner-alignment-2026-10-19/result.md)의 후속이다. 사용자는 정렬 상태 수명 수정 후 재검증을 선택했다. **최종 소스의 반복 SIM은 1 PASS / 1 FAIL로 HOLD다.** main 착지·push·실물 설치·운동·공식 gate 승격은 하지 않았다.

## 소스와 수정

- 수명 수정 commit SHA: `68725ef0f4d0fedee76c4fea2a3ce3d6b68d2601`.
- 곡선 거리 판정 수정 및 최종 시험 commit SHA: `e434578bccbc938d2abb27cf6d5d319dd668aa83`.
- 브랜치 `fix/pinky-observed-recentre-alignment`는 잠긴 작업 워크트리에 보존했다. 원본 성공·이전 통합·전방 정지 후보도 유지했다.

정렬 예산은 같은 장소의 회전을 제한한다. 기존 종료 조건은 직선 corridor만 인정해 관측된 굽은 통로로 이동해도 예산이 다음 코너까지 남았다. 새 종료는 연속 odom에서 실제 원점 이동 0.14m 초과, 그 위치를 벗어난 뒤 촬영된 새 source, 관측 출구와 실제 선택된 현재 target이 현재 좌표의 연결 centre path에 동의하는 조건을 함께 확인한다. 불확실한 odom은 정상화하지 않는다. 일반 전진 후보와 CORE 최종 권한은 유지한다.

첫 수명 후보는 곡선 coverage에도 마지막 x≥0.25m를 요구해 2.408m에서 실패했다. decision64.875초의 연결 경로는 약 0.308m지만 전방 x는 0.202m였다. 최종 수정은 기존 near-start 범위에서 몸→첫 점 연결과 첫→끝 chord를 사용한 경로 길이의 보수적 하한으로 0.25m coverage를 판단한다. chord는 운동 경로나 통행 가능성 증명으로 사용하지 않는다. 중간 pixel zigzag는 이 하한을 부풀리지 못한다. 출구 도달의 종료 조건은 0.25m에서 기존 BEND_ON_X_M(0.18m) 전방 x조건으로 구분했고, 실제 현재 target의 0.18m 조건은 유지했다. CORE 안전 임계값은 바꾸지 않았다.

독립 검토자 `/root/drive_success_review`가 두 변경을 읽었다. 현재 목표의 0.18m 조건 누락을 찾아 복원하고 회귀를 추가한 뒤 중대한 소스 발견 없음으로 재검토했다. 현재 좌표 변환·segment projection·관측 연결성·새 source 위치·불확실 odom 차단과 noisy short path 거부를 확인했다. 귀속은 source commit의 `Safety-Review:`에 있으며 실행·실물 수용과는 별개다.

## 원격 회귀

로그 루트는 외부 `C:/DevTemp/pinky-success-baseline-20261019/`다. 모든 pytest는 native 원격 실행기를 사용했다. 각 GREEN 로그를 known_failures와 별도로 비교했다. 로컬에서는 기록 JSON·영상 hash·기하 집계만 수행했다.

| 소스 / 로그 폴더 | 결과 |
|---|---|
| `caeb6c5495` / `recentre-lifetime-red` | 의도한 1 failed: 굽은 통로 전진 뒤 남은 episode |
| `68725ef0f4` / `recentre-lifetime-green` | 138 passed, NEW 0 |
| `68725ef0f4` / `recentre-lifetime-affected` | 2호출 exit 0, 6,830 passed, 408 skipped, NEW 0; subtests 62 별도 |
| `30ecbd446e` / `recentre-arc-red` | 의도한 1 failed: 곡선 길이와 전방 x거리 혼동 |
| `e434578bcc` / `recentre-arc-green` | 140 passed, NEW 0 |
| `e434578bcc` / `recentre-arc-affected` | 2호출 exit 0, 6,832 passed, 408 skipped, NEW 0; subtests 62 별도 |

최종 affected는 보존 후보 `4d92cc1a8`부터 선택한 2호출이다. AI 역할 호스트에서 실행했고 중복 basename capture 회귀는 별도 호출했다. skip을 통과로 세지 않았고 이전 FULL을 재실행한 것으로 쓰지 않는다. 최종 source까지 13커밋의 size-range도 통과했다. 앞선 실패 문서의 commit SHA 표기 수정 후 문서·경계 회귀는 `d4a13ca4fb`에서 239 passed/NEW 0이었다. 이는 본 후속 문서를 검사한 결과는 아니다.

## 동일 조건 SIM

모델 PC native 8 CPU/6 GB, GPU render, map_v2_fleet lap, speed cap 0.08m/s, stall 60초, record다. 원본 성공과 동일한 `lane_return` 검사 생략을 유지했으므로 그 기능의 수용은 포함하지 않는다. 모델 revision은 `lane-seg-20261010-451f0f85`다.

ONNX SHA256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.

```text
python -X utf8 tools/remote/remote_sim.py --host model --sha <source-commit>
  --log-dir <external-run-directory> --minutes 60 fleet_trips -- --render gpu
  --learned-lane-pointer /home/rosy/rosy-test/v2-sim-lap/model-pointer.txt
  --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return
```

| 소스 / run / 로그 폴더 | 결과 |
|---|---|
| `68725ef0f4` / `sim-68725ef0f4-ea9db8` / `recentre-lifetime-repeat-1` | FAIL: 2.408m stall, goal 1.007m, via 1.526m; 정렬 사용 1표본 |
| `e434578bcc` / `sim-e434578bcc-b934bd` / `recentre-arc-repeat-1` | PASS: arrived, goal 0.109m, via 0.031m; 정렬 미사용 |
| `e434578bcc` / `sim-e434578bcc-da0369` / `recentre-arc-repeat-2` | FAIL: 3.434m stall, goal 1.267m, via 0.766m; 정렬 사용 3표본 후 realign |

세 실행 모두 최종 cmd/odom 선·각속도 0, lease released, left_running 없음이다. native runner exit는 각각 1/0/1이며 원시 출력 fetch와 소유 scope/source 정리도 끝났다. 두 최종 소스 주행은 겹치지 않았다. 첫 실행의 주행과 STOP 후 원시 출력 수집 중 두 번째 초기화를 시작했다. 첫 PASS에 정렬 분기가 없었으므로 그 실행만으로 새 분기의 동작 효과를 입증하지 않는다. 앞선 소스들의 실패는 이전 기록에 그대로 남긴다.

비영 명령 구간과 그 안의 keep_debug 표본:

| 실행 | 구간 초 | learned_drivable / fallback | model revision 표기 / null |
|---|---:|---:|---:|
| 수명 후보 FAIL | 81.573 | 464 / 0 | 462 / 2 |
| 최종 PASS | 257.805 | 1,472 / 0 | 1,465 / 7 |
| 최종 FAIL | 123.266 | 699 / 0 | 696 / 3 |

이는 기록 표본이며 모든 물리 tick의 모델 실행 증거가 아니다. 최종 FAIL의 전체 정지 구간까지 포함한 realign 표본을 비영 명령 구간 수와 혼동하지 않는다.

## 남은 realign과 계약 경계

두 번째 최종 주행에서 decision93.375~93.625초에 실제 왼쪽 관측 정렬이 사용됐고 이후 centre 전진으로 전환했다. decision96.875초 target_now `(0.180, 0.121)`의 방향은 약 +33.9°, 현재 차로 안내 -11.1°, 미래 안내 -120.9°다. `off154.8° > bend109.8°+30°`가 기존 2초를 넘겨 realign 정합성 보호가 작동했다. source96.750초의 frame `000775.png`와 decision을 mask age0.125초로 정확히 결속하고 실제 영상을 확인했다. 모델과 지도 중 어느 쪽이 잘못됐는지는 이 비교만으로 확정하지 않았다.

실행의 CORE 기록은 monotonic62068.1 HOLD `camera_line_not_visible`, 62072.3 LOST `camera_reselection_required`, 62124.8 OFF이며 Fleet 최종 상태는 stopped/stall이다. lease는 해제됐다. 이 보호를 끄거나 realign 허용 각도를 늘리지 않았다.

독립 계약 추적 결과 인식 debug `realign`은 Fleet의 REALIGN 조작 요청이 아니다. observer는 관측 없음으로 전달하고 CORE가 HOLD→LOST를 latch한다. 기존 Fleet bounded REALIGN selector는 활성 trip을 `trip_realign_unproved`로 거절하고 제출 전 검사도 trip의 WAIT 외 답을 막는다. D-622는 trip 복구에 조작 전체 몸체·불확실성이 점유 블록 안에 남는 증명, Gazebo, 별도 안전 검토를 요구한다. 따라서 자동 복구를 설정 하나로 연결할 수 있는 누락 consumer로 판정하지 않았다.

다음 작업은 관측 목표·지도 경로·회전 시점 불일치 교정 또는 별도의 trip 복구 계약 설계다. 같은 최종 소스 1 PASS/1 FAIL이며 반복 주행 수용과 전체 파이프라인 완료로 확대하지 않는다.

## 무결성

최종 PASS:

- run.txt SHA256: `6ca00a930a1d10976a9b20afe70cb27b9a4326f88946a1cd59b1b54794309827`
- result.json SHA256: `89caf0dbc6089d8b8adcb27ed4d9e684b02af1ef94c756cfa212f00cccbfbf19`
- observations.jsonl SHA256: `c72cee8c85a3340ec596179def6d80352c50d5c51c9381b5147a41c673a33bf3`

최종 FAIL:

- run.txt SHA256: `9754eddbe8164fe5fc93745beb2baa7a7af75a858211b4fba3750bb608ccee29`
- result.json SHA256: `ad2dce3fe5123e78996f9323445045acf0f8dca96621c127bd18fd02fb2ea2a2`
- observations.jsonl SHA256: `72fe7dd5dfbbeb132235692d48446631d31a18ca95f9a92d46968136ddace9ec`
- source96.750 PNG SHA256: `11197b45bd9cdab52c2d44d845e6285fd6a49c0c43dccaa82cb3ca2604e8d00a`
