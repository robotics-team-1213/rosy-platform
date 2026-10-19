# Pinky 관측 코너 정렬 후보 검증 — HOLD

2026-10-19 KST. [앞선 성공 기준·통합 검증](../pinky-success-baseline-2026-10-19/result.md)의 코너 정체 후속이다. **반복 완주 수용과 코너 작업은 미완료다.** 원격 회귀를 통과했지만 SIM은 정렬 상태 수명 문제로 실패했다. main 착지·push·실물 설치·운동과 gate 승격은 하지 않았다.

## 소스와 변경

- 보존한 이전 후보 commit SHA: `4d92cc1a8146f9074f73bf36464168dae442c571`.
- 선행 기하 이동 commit SHA: `7d14f20241c5664c364070afc34ab2d5b25c954a`. steer의 기존 경계 교차 계산·상수를 기존 target 모듈로 옮기고 import 이름을 재노출했다.
- 첫 관측 정렬 commit SHA: `4766cfbf8868533b61f648a5b5ecad2c84cbbef0`. 짧은 전진 목표·신선한 현 차로 안내·실제 관측 통로가 동의할 때 zero-linear 정렬을 낸다. source/current pose·신선도·연속 odom·누적 절대 yaw 예산을 검사하고 기대 전진 경로용 target은 제거한다.
- 반대 pivot 처리 commit SHA: `8949ff012507a37d712b880fc09fc3258e88e4d0`. 이미 선택된 반대 zero-linear pivot도 같은 정렬 예산으로 처리한다. 예산 소진·관측 소실·odom 불확실성 뒤 반대 latch를 복원하지 않는다. 앞쪽 장애물·straddle·횡단보도·pivot-limit 보호는 유지한다.
- 최종 시험 소스 commit SHA: `00e9913f2988e27aff2acef8cee29c6cbfcd7974`. 직전 runtime과 같고 회귀의 현재 안내 fixture만 캡처 값으로 바꿨다.
- 브랜치: `fix/pinky-observed-recentre-alignment`. 이전 성공·통합·전방 정지 후보를 유지하고 작업 워크트리는 잠금 상태로 보존했다.

독립 검토자 `/root/drive_success_review`가 기하 이동과 두 정렬 변경의 실제 생산자·소비자·안전 경계를 읽고 중대한 소스 발견이 없다고 확인했다. 해당 커밋의 `Safety-Review:`에 귀속했다. 이 검토는 실행·장치 수용과 별개다. CORE 최종 명령 권한과 안전 임계값은 바꾸지 않았다.

## 원격 회귀

모든 pytest는 native 원격 실행기로 수행했다. 아래 폴더는 외부 로그 루트 `C:/DevTemp/pinky-success-baseline-20261019/` 아래다. 숫자는 중복 실행끼리 합산하지 않는다.

| 소스 / 폴더 | 결과 |
|---|---|
| `779a9f4fc5` / `recentre-red` | 의도한 2 failed: 첫 관측 정렬 오류 |
| `7d14f20241` / `recentre-geometry` | 74 passed, NEW 0 |
| `4766cfbf88` / `recentre-green-1` | 115 passed, NEW 0 |
| `4766cfbf88` / `recentre-affected` | 2호출 exit 0; 6,691 passed, 408 skipped, NEW 0; subtests 62 별도 |
| `a40026bb98` / `recentre-latch-red` | 의도한 2 failed, 34 passed: 이미 선택된 반대 pivot 우회 |
| `8949ff0125` / `recentre-latch-green` | 124 passed, 1 failed: 축소 offset fixture의 다른 사례 안내값을 캡처 값으로 수정 |
| `00e9913f29` / `recentre-latch-green-final` | 125 passed, NEW 0 |
| `00e9913f29` / `recentre-latch-affected` | 2호출 exit 0; 6,701 passed, 408 skipped, NEW 0; subtests 62 별도 |

기준 diff는 보존 후보 `4d92cc1a8`부터다. 선택기는 affected 2호출이며 바뀌지 않은 이전 FULL을 반복하지 않았다. 같은 이름의 capture 회귀는 별도 호출이다. 최종 영향 회귀는 AI 역할 호스트에서 수행했고 두 로그를 각각 known_failures와 비교했다. skip은 실행 성공으로 계산하지 않는다. 첫 affected 준비의 logs 인자 형식 오류는 시험 시작 전에 종료·native cleanup됐고 재실행 결과만 수에 넣었다. source 범위 7커밋의 size-range는 통과했다.

## 동일 조건 SIM

모델 PC native 8 CPU/6 GB, GPU render, map_v2_fleet lap, speed cap 0.08m/s, stall 60초, record다. 원본 성공과 같은 `lane_return` 검사 생략이므로 이 기능의 수용은 포함하지 않는다. 모델 revision은 `lane-seg-20261010-451f0f85`이며 실행 중 원격 model.onnx를 다시 hash했다.

ONNX SHA256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.

```text
python -X utf8 tools/remote/remote_sim.py --host model --sha <source-commit>
  --log-dir <external-run-directory> --minutes 60 fleet_trips -- --render gpu
  --learned-lane-pointer /home/rosy/rosy-test/v2-sim-lap/model-pointer.txt
  --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return
```

| 소스 / 실행 / 폴더 | 결과 | 정지·정리 |
|---|---|---|
| `4766cfbf88` / `sim-4766cfbf88-4dc846` / `recentre-repeat-1` | FAIL: 기존 두 정체 위치를 지나 ring_s 6.658m stall; 경유점 0.032m, 최종 목표 거리 0.788m | 최종 cmd/odom 선·각속도 0, lease released, left_running 없음 |
| `00e9913f29` / `sim-00e9913f29-26f127` / `recentre-latch-repeat-1` | FAIL: 1.813m stall, 최종 목표 거리 0.505m | 최종 cmd/odom 선·각속도 0, lease released, left_running 없음 |

최종 후보 전 1회는 호스트 CPU 여유 부족으로 시작하지 않았으며 주행 분모에 넣지 않았다. 두 실제 주행 모두 runner exit 1이고 원시 출력 fetch와 native 정리는 끝났다. 성공 기준 소스와 이전 통합·전방 정지 실패는 앞선 기록에 그대로 남긴다.

첫 후보 비영 명령 구간은 286.612초이고 learned_drivable 표본 1,647/fallback 0, model revision 1,607/null 40이다. 최종 후보는 60.923초, learned_drivable 351/fallback 0, model revision 349/null 2다. 이는 기록 표본이며 모든 물리 tick의 모델 실행 증거가 아니다.

## 실패 결속과 상태 수명

첫 ring_n 증거는 camera 120.500초·decision 120.625초다. 관측 통로와 현재 안내가 왼쪽인데 미래 안내가 오른쪽이었다. 외부 `corner-analysis/corner-evidence.html`과 `matched-snapshot.json`에 실제 영상·4픽셀 preview mask·지상 좌표를 결속했다. preview는 전체 해상도 모델 재생이 아니다.

첫 수정 SIM의 ring_s에서는 source173.750초·decision173.875초에 관측 near centre `(0.163, 0.098)`, target `(0.122, 0.117)`, 실제 왼쪽 opening `(0.190, 0.094)`와 현재 안내 +25.3°가 동의했다. 미래 안내 -80.2°의 오른쪽 pivot이 유지됐고 실제 cmd angular=-0.6rad/s였다. 새 정렬이 raw pivot 경로를 받지 않아 우회되는 오류를 다음 RED와 소스로 고쳤다.

최종 후보는 decision45.875초에 왼쪽 정렬을 한 번 사용한 뒤 관측된 굽은 길을 따라 전진했다. decision50.500초에는 정렬 원점 대비 약 0.155m 이동했다. source50.375초의 centre path는 `(0.139, 0.0002)`부터 `(0.290, -0.229)`까지 이어지고 실제 오른쪽 opening은 `(0.221, -0.110)`, candidate는 `drivable_turn_right`였다. 그러나 종료 조건 `drivable_centre + ahead≥0.25m`가 굽은 통로 전진을 인정하지 않아 예산이 다음 회전까지 남았다. 소진 뒤 정상 오른쪽 pivot도 막아 CORE HOLD `camera_line_not_visible`, 이후 LOST `camera_reselection_required`로 전환했다.

다음 수정 경계는 한 장소의 정렬 episode를 새 관측 근거 아래 실제로 벗어나면 종료하는 것이다. 연속 odom에서 0.14m 초과 이동, 이동 중 받은 새 관측, 현재 좌표에서 연결된 centre path와 실제 선택 target·관측 출구의 일치를 함께 입증해야 한다. strategy 이름이나 path의 먼 끝 하나로 종료하지 않는다. guide/memory/bridge/제자리 정렬만의 진행과 odom 불확실성은 종료 근거가 아니다. 굽은 길 전진 뒤 새 코너를 허용하는 회귀와 제자리 회전·mask flicker·guide-only creep·위치 점프가 재충전하지 않는 회귀를 짝지어야 한다. 추가 runtime 변경은 진행 방향을 사용자에게 확인하기 전 멈췄다.

## 무결성

첫 후보 실패:

- run.txt SHA256: `86ac33b505b5ad457fd92a980912fec59d57c890c778fc03fe6b6aa0975d9426`
- result.json SHA256: `253ea80a2b0a73d48aa8a0e963190b9852492b88c40324c38aa133db18609aaf`
- observations.jsonl SHA256: `e0a51c21b5a180ec227669e83a2eb0c4ce3cc144b1c24a98ecf34fac77a6abc5`
- source173.750 PNG SHA256: `e5054212368e2d9dd29da4620baefab9e207193dd6167256d5b7076412e16d15`

최종 후보 실패:

- run.txt SHA256: `76ff4930ea4af1a1f13167be7dec829211c233a482cab6a3b3409cd323a4c869`
- result.json SHA256: `2e332152f44eaa7e627fc2a216378e2e0d191002f7abfbde7f3eda0106a2efc3`
- observations.jsonl SHA256: `6594b5c630b7fbd83b25baa24fa9fe2ed72256c6450154ea1825f2111659cf83`
- source50.375 PNG SHA256: `1065f17ce7fef3537ea41f91187de93971757387e6cd36d98f44786e966ef5b7`
