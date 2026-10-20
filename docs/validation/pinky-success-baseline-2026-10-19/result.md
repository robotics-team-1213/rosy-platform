# Pinky drivable v2 성공 기준 보존과 재실행

2026-10-19. 성공한 구현을 현재 main에 옮기기 전에 원본 소스·모델·조건을 고정하고
원래 성공 호스트에서 새 초기화로 한 번 더 실행했다. 실물은 접속·변경·운동시키지 않았다.

## 성공 기준

- source commit `91f14c997fcd1c509b2ee6bb9f72b2fdc8548090`.
- 성공 구현을 모은 기존 commit `39d2ffae42f0ab598b9ab07ac7f10acd83f69856`;
  후속 워크트리 commit `ff8eca4d9b4adcecaccdabf7b9e3886c4eaca789`와 구분한다.
- model revision `lane-seg-20261010-451f0f85`.
- ONNX SHA256 `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.
- 보존 source archive SHA256 `0b06b128773eea23f62ea796a2716409e6075996a813e865a150115ad349c393`.
  archive와 ONNX는 외부 scratch `pinky-v2-device-test-20261019/`에 있으며 이번에 다시 hash했다.

원본 r51a는 PASS, r51b는 Fleet arrived에도 최종 목표 오차 때문에 FAIL이다.
두 번 모두 통과했다고 합산하지 않는다. 기존 재점검의 실패도 그대로 보존한다.

## 새 원본 소스 재실행

실제 runner는 source commit을 지정해 모델 PC에서 실행했다. 모델 pointer는 해당 호스트의
기존 고정 모델을 사용했다. 공개 명령의 pointer만 placeholder다.

```text
python tools/remote/remote_sim.py --host model
 --sha 91f14c997fcd --minutes 60
 --log-dir <external-scratch>/pinky-success-baseline-20261019/r51a-repeat-1
 fleet_trips -- --render gpu --learned-lane-pointer <host-model-pointer>
 --learned-paint-target drivable --lap --stall-s 60 --record --skip-check lane_return
```

논리적 한 명령을 줄바꿈해 표시했다. run ID `sim-91f14c997f-4b1237`, 원격 role model,
runner profile 8 CPU/6GB, 원격 runner 종료 exit 0, 결과 파일 `pass: true`다.

| 측정 | 결과 |
|---|---|
| Fleet 상태 | started → running → arrived |
| 정착 후 목표 거리 | 0.105m; 기존 시험 기준 0.15m |
| 반대편 경유점 최근접 거리 | 0.031m |
| 주행 시간 구간 | 첫 비영 최종 명령부터 마지막 비영 명령까지 약 269.209초 |
| 위 구간 keep_debug 인식 | learned_drivable 1,539건, fallback 0건 |
| 기록된 model revision | lane-seg-20261010-451f0f85 |
| 마지막 최종 명령 선/각속도 | 0 / 0 |
| 마지막 odom 선/각속도 | 0 / 0 |
| 마지막 Fleet lease | released |
| 종료 후 소유 잔존 프로세스 | 없음 (`left_running: []`) |

인식 수치는 recorder가 보존한 keep_debug 샘플의 집계다. 모든 물리 tick을 측정한
수치가 아니다. `moved_m`는 한 바퀴 시작점과 정착점의 거리이며 전체 주행 거리가 아니다.
차선 복귀 검사 `lane_return`는 원본과 같이 생략했다. 전체 검사·다중 로봇·실물 수용으로
확대하지 않는다. 모델·archive의 로컬 보존 hash를 확인했으며 원격 모델 파일의 이번
재해시는 수행하지 않았다. 실행 관측의 model revision으로 실제 소비를 대조했다.

## 보존 원시 증거

로컬 외부 scratch: `C:/DevTemp/pinky-success-baseline-20261019/r51a-repeat-1/`.
runner가 가져온 파일을 읽고 아래 hash와 결과를 계산했다.

| 파일 | 무결성 |
|---|---|
| run.txt | SHA256 `45680321fc945f5dd8b0ca25bc1a7a6012a37d81e7be40ca4d26ef3ed82ce582` |
| out/trips/result.json | SHA256 `5db72b8af1a4dc017ef7bc67beabf6d906ac2553f3d3e7c03a17db66f614c708` |
| out/trips/launch.log | SHA256 `9a122e1e56f44ad87311919b2bb8256e53dd7308ac76ad8b77af28f7a73be03f` |
| out/trips/observations.jsonl | SHA256 `caeeaba59b0152f96117083a0b5f4ceacd450b7b971b30475d66549331600efc` |
| out/trips/api-log.jsonl | SHA256 `e504036544473293a4cd4cd271152da6b1a35849834a9fee0dd8f7893f1917de` |

## 현재 main과의 차이 및 검증 경계

조사 base commit `a27b980c7cb780b042ba6a85b5e541d9e533d823`에는 위 성공 구현이 없었다.
차이는 source 수명·선택 지도 벽 schema, CORE/Drive 소비, recentre, Fleet 생산 및 SIM
지도·설정에 있다. 단순히 성공 코드를 다시 작성하지 않고 기존 소스를 순서대로 옮긴다.

원본 검증 브랜치 commit `19ac6490a731a1494bb28a0237f1f55c5369c4c6`의 관련 여섯 파일
원격 회귀는 159 passed, NEW 0이었다. 별도 foundation 선행 commit `3e56f3668c`의
계약·문서·기존 Fleet API 핀 검사는 1,209 passed, NEW 0이었다. 원본 SIM 결과를 현재
통합 후보의 실행 결과로 합산하지 않는다. 후속 후보는 같은 호스트·모델·인자로 실행하고
현재 source SHA의 결과로 별도 판정한다.

## 통합 반복 결과: HOLD

동일 모델 PC·모델 pointer·인자로 실행한 통합 후보의 결과를 모두 보존한다.

| source | run ID | 결과 |
|---|---|---|
| d9b706e204 | sim-d9b706e204-2b8d7b | PASS; 목표 0.113m, 경유점 최근접 0.049m, 최종 명령·odom 정지 |
| 13f44844af | sim-13f44844af-9223d8 | FAIL; west 진행 4.698m에서 stall |
| bafb32dc10 | sim-bafb32dc10-0cfcfb | FAIL; ring_n 진행 3.420m에서 stall |

`bafb32dc10`은 당시 main `4b2cb988cc`를 병합한 뒤, 횡단보도 직진 유지가 측정한
LiDAR 전방 막힘의 pivot 판단을 지우지 않게 한 수정이다. 원격 회귀를 먼저 RED로
재현했고 수정 후 인식·CORE 횡단보도 회귀는 132 passed, NEW 0이었다. 독립 계약 검토에
중대한 소스 발견은 없었으나, 이 결과를 반복 완주나 실물 수용으로 올리지 않는다.

수정본은 LOCALIZED 상태에서 실제 pursuit target의 전방 길이가 0.111m인 상황에서,
반대편 관측 중심 때문에 출구 선회를 취소한 뒤 `drivable_closed`로 정지했다. 가까운
행 중심 중앙값을 목표로 대체하거나 보호 조건을 건너뛸 근거는 부족해 추가 운동 변경을
하지 않았다. 같은 시각 mask·경계·centre path·odom 변환 기억 출구를 대조해야 한다.
이 정체는 앞선 횡단보도 오류와 다른 지점이다.

첫 통합 result SHA256: `dea67341436f3c0301ab89e742946097c8f57f912b8facd344909e9efe9d4f62`.
두 번째 result SHA256: `d6a9630623793ffbee13ba233872c197cae92b069f86c4f6ef6d86912bb35fcf`.
수정본 result SHA256: `b96670601bc439ee0f4dffe0d4ad0912bd72a96c3c12676fa0c5497ab4bd10df`.
외부 scratch의 `integrated-repeat-1`, `integrated-repeat-2`, `front-stop-repeat-1`에
각 result·관측·API·영상 프레임을 보존했다. main 착지·push·실물 배포는 하지 않았다.
