# Pinky 코너 정체 수정과 반복 검증

2026-10-19 KST. [앞선 통합 검증](../pinky-success-integration-2026-10-19/result.md)의 남은 코너 정체를 처리한 후속 기록이다.

## 현재 판정

현재 후보 commit `e434578bccbc938d2abb27cf6d5d319dd668aa83`는 곡선 길이의 보수적 하한과 출구·목표의 전방 x조건을 구분한다. 독립 안전 검토, 관련 원격 **140 passed / NEW 0**, 영향 범위 **6,832 passed / 408 skipped / NEW 0**을 통과했다. 같은 소스의 SIM은 **1회 PASS / 1회 FAIL**이다. 두 번째 실행에서 새 정렬 분기를 실제 사용한 뒤 관측 목표와 현 차로 안내의 약 45° 불일치로 기존 `realign` 보호가 정지했다. **반복 완주와 전체 주행 파이프라인은 계속 HOLD다.**

최종 문서 head `db2b67580a`는 문서·배포 경계 원격 검사 **239 passed / NEW 0**이다. runtime은 위 e434 소스와 같다. [저장소 검증 기록](../../../.worktrees/pinky-rl-binding/docs/validation/pinky-corner-lifetime-2026-10-19/result.md)에 원시 출력 위치·hash·실행별 한계를 보존했다.

후속 상태 수명 후보 `68725ef0f4`는 관련 원격 **138 passed**, 영향 범위 **6,830 passed / 408 skipped / NEW 0**을 통과했지만 SIM은 2.408m 정체로 실패했다. 곡선 경로 길이를 전방 x거리로 판단하던 오류를 추가 RED로 결속했다.

앞선 후보 commit `00e9913f2988e27aff2acef8cee29c6cbfcd7974`의 관련 원격 회귀는 **125 passed / NEW 0**, 영향 범위 회귀는 **6,701 passed / 408 skipped / NEW 0**이었다. 이 후보는 정렬 상태 수명 문제로 SIM에 실패했다. 해당 runtime은 `8949ff012507a37d712b880fc09fc3258e88e4d0`에 있고 후속 변경은 시험 fixture 한 줄이었다.

## 원인과 수정 범위

첫 실패는 `ring_n`에서 전진 목표가 짧아진 뒤 정지한 경우였다. 관측 통로와 현재 차로 안내는 왼쪽인데 미래 우회전 안내가 오른쪽을 가리켰다. source camera 120.500초와 decision 120.625초를 mask age 0.125초로 결속했다. 실제 영상과 4픽셀 간격 preview mask, 지상 좌표는 [진단 그림](C:/DevTemp/pinky-success-baseline-20261019/corner-analysis/corner-evidence.html)에 보존했다. 이 preview는 전체 해상도 모델 재실행이 아니다.

이 경우 관측 통로 쪽으로 선속도 0의 정렬 후보를 내도록 했다. source/current pose 변환, 관측 신선도, 현재 차로 안내와의 동의가 필요하다. 회전은 시작 시 관측한 각도와 기존 상한 안에서 누적 절대 yaw로 제한한다. 좌우 진동, 초기화, 위치·시간 점프, 관측 깜빡임으로 예산을 다시 주지 않는다. 새 예산에는 독립 전방 관측과 연속 odom상의 실제 전진이 필요하다.

첫 수정 후보 commit `4766cfbf8868533b61f648a5b5ecad2c84cbbef0`는 이전 실패 지점을 통과했지만 `ring_s` 6.658m에서 정체했다. 이미 선택된 오른쪽 pivot은 기존 recentre와 새 정렬의 진입 조건을 모두 우회했다. source 173.750초의 [실제 영상](C:/DevTemp/pinky-success-baseline-20261019/recentre-repeat-1/out/trips/frames/rosy_01/001391.png), decision 173.875초와 발행된 각속도 -0.6rad/s를 결속했다. 현재 관측 near centre `(0.163, 0.098)`, target `(0.122, 0.117)`, 왼쪽 opening `(0.190, 0.094)`와 현재 안내 +25.3°가 동의하는데 미래 안내 -80.2°의 오른쪽 pivot이 유지됐다.

최종 수정은 그 반대 pivot도 같은 정렬 예산으로 처리한다. 기존 pivot의 strategy·error·confidence가 정확히 일치하고, 실제 관측 통로와 현재 안내가 반대쪽에 동의할 때만 진입한다. 예산 소진·관측 소실·odom 불확실성 뒤 반대 latch로 복귀하지 않는다. 앞쪽 장애물, straddle/off-line, 횡단보도와 pivot-limit 보호는 유지한다. 정렬 후보에서 기대 전진 경로로 오인할 target은 제거했다. CORE의 최종 명령 권한과 안전 임계값은 바꾸지 않았다.

600줄 한도에 있던 steer의 기존 경계 교차 기하는 별도 선행 커밋 commit `7d14f20241c5664c364070afc34ab2d5b25c954a`에서 기존 target 모듈로 이동했다. 계산·상수·기존 import 이름을 유지했다. 독립 검토자 `/root/drive_success_review`가 이 이동과 두 정렬 수정의 생산자·소비자·안전 경계를 읽고 중대한 소스 발견이 없다고 확인했다. 이 검토는 실행 검증과 구분한다.

## 원격 시험

모든 pytest는 native 원격 실행기로 수행했다. 노트북에서 pytest나 제품 모듈 재생을 실행하지 않았다. 외부 로그의 JSON 집계와 그림 생성은 표준 라이브러리로 처리했다.

| 소스 / 로그 폴더 | 결과 | 의미 |
|---|---|---|
| `779a9f4fc5` / `recentre-red` | 의도한 2 failed | 첫 관측 정렬 오류 RED |
| `7d14f20241` / `recentre-geometry` | 74 passed, NEW 0 | 기하 이동 회귀 |
| `4766cfbf88` / `recentre-green-1` | 115 passed, NEW 0 | 첫 정렬과 예산·odom·기대 경로 보호 |
| `4766cfbf88` / `recentre-affected` | 6,691 passed, 408 skipped, NEW 0 | 영향 범위 2호출; subtests 62건은 별도 |
| `a40026bb98` / `recentre-latch-red` | 의도한 2 failed, 34 passed | 이미 선택된 반대 pivot 우회 RED |
| `8949ff0125` / `recentre-latch-green` | 124 passed, 1 failed | 축소 offset fixture에 다른 사례의 현재 안내값을 사용한 오류; 임계값을 바꾸지 않고 캡처한 +25.3°로 수정 |
| `00e9913f29` / `recentre-latch-green-final` | 125 passed, NEW 0 | 최종 관련 회귀 |
| `00e9913f29` / `recentre-latch-affected` | 6,701 passed, 408 skipped, NEW 0 | 해당 후보 영향 범위 2호출; subtests 62건은 별도 |
| `caeb6c5495` / `recentre-lifetime-red` | 의도한 1 failed | 굽은 통로 전진 뒤 episode가 남는 오류 |
| `68725ef0f4` / `recentre-lifetime-green` | 138 passed, NEW 0 | 수명 조건 수정 회귀 |
| `68725ef0f4` / `recentre-lifetime-affected` | 6,830 passed, 408 skipped, NEW 0 | 2호출; subtests 62건은 별도 |
| `30ecbd446e` / `recentre-arc-red` | 의도한 1 failed | 곡선 coverage와 전방 x거리 혼동 |
| `e434578bcc` / `recentre-arc-green` | 140 passed, NEW 0 | 실제 tight curve 허용과 noisy short path 거부 |
| `e434578bcc` / `recentre-arc-affected` | 6,832 passed, 408 skipped, NEW 0 | 2호출; subtests 62건은 별도 |
| `d4a13ca4fb` / `recentre-final-docs-v2` | 239 passed, NEW 0 | 이전 실패 기록의 문서·경계 검사; 최초 238 passed/1 failed는 commit SHA 표기 누락에 대한 secret-scan 오인으로 수정 |

로그 루트: `C:/DevTemp/pinky-success-baseline-20261019/`. 첫 affected 실행 준비 중 호출자의 logs 인자 형식 오류가 있었으나 시험 시작 전 종료됐고 native cleanup이 실행됐다. 올바른 로그 목록으로 다시 실행한 2호출만 시험 수에 넣었다. RED 실패와 fixture 수정 전 실패를 최종 GREEN 수에 합치지 않는다.

## SIM 조건과 결과

원본 성공과 같은 모델 PC native 8 CPU/6 GB, GPU render, map_v2_fleet lap, speed cap 0.08m/s, stall 60초, record 조건이다. `lane_return` 검사는 원본과 똑같이 생략했으므로 이 동작의 수용 근거가 아니다. 실물 로봇은 움직이지 않았다.

모델 revision: `lane-seg-20261010-451f0f85`.
ONNX SHA256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.

```text
python -X utf8 tools/remote/remote_sim.py --host model --sha <source-commit>
  --log-dir <external-run-directory> --minutes 60 fleet_trips -- --render gpu
  --learned-lane-pointer /home/rosy/rosy-test/v2-sim-lap/model-pointer.txt
  --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return
```

| 소스 / 실행 | 판정 | 관측 |
|---|---|---|
| `4766cfbf88` / `sim-4766cfbf88-4dc846` | FAIL | ring_s 정체 6.658m; 경유점 최근접 0.032m; 도착 오차 0.788m |
| `00e9913f29` / `sim-00e9913f29-26f127` | FAIL | 1.813m에서 정체; 정렬 예산 상태가 실제 전진 후에도 남아 정상 우회전을 차단 |
| `68725ef0f4` / `sim-68725ef0f4-ea9db8` | FAIL | 이전 실패를 지나 2.408m에서 정체; 연결된 곡선 길이와 전방 x거리 혼동 |
| `e434578bcc` / `sim-e434578bcc-b934bd` | PASS | 목표 0.109m, 경유점 0.031m; 새 정렬 분기는 사용하지 않음 |
| `e434578bcc` / `sim-e434578bcc-da0369` | FAIL | 정렬 3표본 사용 후 realign 정지; 최종 Fleet 정체 진행 3.434m, 목표 거리 1.267m |

두 e434 실행 모두 최종 cmd/odom 선·각속도 0, lease released, 소유 잔존 프로세스 없음이며 원시 출력 fetch와 native 정리는 끝났다. 첫 PASS의 비영 명령 구간은 257.805초, learned_drivable 1,472/fallback 0, model revision 1,465/null 7이다. 두 번째 FAIL은 123.266초, learned_drivable 699/fallback 0, model revision 696/null 3이다. 성공한 첫 실행에서 정렬 분기가 사용되지 않았으므로 그 실행만으로 새 분기의 현장 효과를 입증했다고 쓰지 않는다.

두 번째 주행의 decision93.375~93.625초에는 관측 정렬 왼쪽 pivot이 실제 사용됐다. 이후 centre 후보로 전환했고 decision96.875초의 target_now `(0.180, 0.121)`는 약 +33.9°, 현 차로 안내는 -11.1°, 미래 안내는 -120.9°였다. `off=154.8° > bend109.8°+허용30°` 상태가 기존 2초를 넘겨 `realign` HOLD가 발생했다. 이는 회전 예산 소진과 구분되며, 해당 보호를 우회하거나 허용 각도를 늘리지 않았다.

최종 후보 첫 SIM은 decision 45.875초에 왼쪽 정렬을 한 번 사용했다. 이후 관측된 굽은 길을 따라 전진했다. stamp 50.500초에는 정렬 원점 대비 약 0.155m 이동했고, 새 관측에 기반한 `drivable_turn_right`였다. 그런데 episode 종료 조건은 `drivable_centre + ahead≥0.25m`만 인정해 굽은 통로의 진행을 인정하지 않았다. 누적 yaw가 소진된 뒤 정상 오른쪽 pivot까지 막아 CORE가 `camera_line_not_visible` HOLD, 이후 `camera_reselection_required` LOST로 전환했다. 실패는 이 수명 문제로 설명되지만, 단순 조건 완화의 안전성은 별도 검토가 필요하다.

해당 전진 증거의 source stamp는 50.375초, decision은 50.500초이고 [영상](C:/DevTemp/pinky-success-baseline-20261019/recentre-latch-repeat-1/out/trips/frames/rosy_01/000404.png)을 직접 확인했다. 관측 centre path는 `(0.139, 0.0002)`에서 `(0.290, -0.229)`까지 이어지고 실제 관측 오른쪽 opening은 `(0.221, -0.110)`이다. strategy 이름이나 path의 먼 끝 하나만으로 새 예산을 주는 방식은 채택하지 않았다.

최종 후보의 비영 명령 구간은 약 60.923초, learned_drivable 표본은 351건/fallback 0건, model revision 표기는 349건/null 2건이다. 최종 cmd/odom 선·각속도는 모두 0, lease released, 소유 잔존 프로세스 없음이다. 초기 SIM 재시도 1회는 호스트 여유 CPU 부족으로 시험을 시작하지 않았고 주행 분모에 넣지 않았다. 실행 중 원격 model.onnx SHA256도 위 모델과 일치함을 다시 확인했다.

첫 후보의 비영 명령 구간은 약 286.612초, keep_debug의 learned_drivable 표본은 1,647건이고 fallback 표본은 없었다. model revision 표기는 1,607건이며 40건은 null이다. 기록된 표본 수를 모든 물리 tick의 모델 실행 증거로 확대하지 않는다. 최종 cmd/odom 선·각속도는 모두 0, lease는 released, 소유 잔존 프로세스는 없었다.

첫 후보 실패 원시 기록의 SHA256:

- run.txt SHA256: `86ac33b505b5ad457fd92a980912fec59d57c890c778fc03fe6b6aa0975d9426`
- result.json SHA256: `253ea80a2b0a73d48aa8a0e963190b9852492b88c40324c38aa133db18609aaf`
- observations.jsonl SHA256: `e0a51c21b5a180ec227669e83a2eb0c4ce3cc144b1c24a98ecf34fac77a6abc5`
- source173.750 PNG SHA256: `e5054212368e2d9dd29da4620baefab9e207193dd6167256d5b7076412e16d15`

최종 후보 실패 원시 기록의 SHA256:

- run.txt SHA256: `76ff4930ea4af1a1f13167be7dec829211c233a482cab6a3b3409cd323a4c869`
- result.json SHA256: `2e332152f44eaa7e627fc2a216378e2e0d191002f7abfbde7f3eda0106a2efc3`
- observations.jsonl SHA256: `6594b5c630b7fbd83b25baa24fa9fe2ed72256c6450154ea1825f2111659cf83`
- source50.375 PNG SHA256: `1065f17ce7fef3537ea41f91187de93971757387e6cd36d98f44786e966ef5b7`

## 다음 수정의 구체적 경계

정렬 예산은 한 장소의 제한된 회전이다. 그 장소를 새 관측 근거 아래 실제로 벗어났을 때 episode를 끝내고, 이전 코너의 yaw를 다음 코너에 전파하지 않는 방향이 독립 구조 검토와 일치한다. 단순히 매 프레임 또는 guide가 바뀔 때 예산을 다시 주면 안 된다.

다음 수정은 연속 odom에서 원점 대비 0.14m 초과 이동, 이동 중 받은 새 관측, 현재 좌표에서도 앞쪽으로 연결된 centre path와 실제 선택 target·관측 출구의 일치를 함께 입증해야 한다. guide/memory/bridge/제자리 정렬만으로 만든 전진은 제외하고, 불확실한 odom episode는 이 조건으로 정상화하지 않는다. 회귀는 굽은 통로의 실제 전진 뒤 새 코너는 허용하는 사례와 제자리 회전·mask flicker·guide-only creep·위치 점프는 종료하지 않는 사례를 짝지어야 한다.

이 세 번째 SIM 실패 후 구조를 재검토하고 사용자에게 진행 방향을 확인했다. 사용자는 **정렬 상태 수명 수정 후 재검증**을 선택했다. 후속 소스는 실제 관측 출구와 선택한 현재 target을 현재 좌표의 연결 polyline에 투영해 거리·전방 길이를 확인하고, 원점을 0.14m 초과 벗어난 위치에서 받은 새 관측일 때 이전 episode를 종료한다. 불확실 odom은 계속 거부한다. 곡선 coverage와 전방 x거리 혼동도 RED로 고친 후 관련 GREEN 140건과 영향 범위 회귀를 통과했다. SIM 반복 수용은 위 realign 실패로 HOLD다.

기존 Fleet의 bounded `REALIGN`은 opt-in과 검증 영역이 기본 비어 있고, trip이 있으면 명시적으로 `trip_realign_unproved`로 거절한다. 따라서 이번 Fleet trip의 정지를 설정 하나로 자동 복구 경로에 연결할 수 없다. 다음 단계는 trip 중 재관측·재선택의 권한과 복귀 조건을 설계하거나, 관측·경로 안내 불일치를 모델·지도 쪽에서 교정하는 것이다. 기존 보호를 끄는 방법은 제안하지 않는다.

다음 설계의 우선 검토 후보는 경로 안내에 회전점까지 남은 거리를 전달하는 것이다. 실패 직전 guide station 3.4163m와 계획상 ring_n 종료 3.4447m의 차이는 약 0.0284m다. 현재 schema는 현 지점·앞쪽 지점 방향을 전달하지만 회전점까지 거리는 없다. 이 정보가 회전 시점 혼동을 해소하는지는 아직 검증하지 않았으므로 확정 원인이나 완료된 수정으로 쓰지 않는다. 별도 trip 복구 계약을 먼저 설계할지와 함께 사용자에게 방향을 확인 중이며, 새 계약에 대한 생산 코드 변경은 하지 않았다.

## 적용과 남은 수용

후보 브랜치는 `fix/pinky-observed-recentre-alignment`, 워크트리는 잠금 상태로 보존했다. 원본 성공·이전 통합·전방 정지 수정 브랜치는 유지했다. main 착지·push·실물 설치 및 주행은 수행하지 않았다. 이번 범위는 코너 정체 수정과 원격 회귀·동일 조건 SIM이며, 전체 파이프라인과 실물 과제 완료를 뜻하지 않는다.
