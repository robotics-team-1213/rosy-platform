## D-213 DEVICE→FIELD 승격 순서 — 실물 1대 stationary부터 2대(실물+sim) 현장 반복까지

**Status:** Proposed (2026-09-25).

**Context:**

1. D-210이 1차 범위를 `(2대 관제+군집, 실물 1대 + sim 1대, 도크/신호 제외)`로 고정했다. D-46/D-53은 Device 설치·서명 readback 증거 계약을 정한다. G0–G5 커미셔닝과 `pi5-acceptance-checklist.md`의 BUILD/BOOT/NETWORK/UPDATE 게이트는 전부 HOLD다.
2. 수용 기준 §9의 승격 순서는 core-only 설치 → stationary graph/readback → lifted-wheel → floor course → 결합 → FIELD 반복이다.

**Decision:**

1. 승격 순서를 고정한다. 건너뛰기 금지, 실패 시 이전 generation 유지:
   1. SD write + readback 검증 후 Pi 부팅 (`BOOT_GO`), runtime mode `core` 고정, motor/io 미기동(`MOTOR_HOLD` 유지).
   2. `install-pi.sh`(ROSY_ROBOT_NUMBER 필수) → `verify-pi.sh` → `device-readback.sh --json` 보관(identity, manifest digest, 서명 상태, health, graph, `cmd_vel` publisher 수).
   3. stationary CORE graph: 최종 `cmd_vel` publisher 1개, readiness/HOLD 동작, e-stop 래치·해제(새 operator action + fresh evidence) 확인.
   4. lifted-wheel bench: deadman/timeout/UART-loss 시 측정 시간 내 zero, motor/ready lease 만료, 재시작 후 명령 미재개.
   5. 측정 floor course 단일 로봇: Nav2 goal→정지/실패, profile 한계 우회 불가(P0-1), demo-map fallback 금지(P0-2), footprint 실측(P0-3), 정지 지연/거리 기록.
   6. 2대 묶음(실물 1 + sim 1, 동일 맵): console goal/cancel/e-stop, formation arm→relay→watch→HOLD/ABORT/resume, 스트림 단절 HOLD, 일부 로봇 timeout의 전체 성공 합산 금지.
   7. FIELD 반복: 대표 실내 조건에서 반복 횟수·성공률/오차/지연 기록 + 운영자·안전 승인 + rollback 결과. 배터리 실측(`BATTERY_GO`) 포함.
2. 도크·신호등·OMX·보조 센서 결합은 D-210 제외이므로 이 승격에서 다루지 않는다. 각 모듈 결합은 해당 모듈 DEVICE 기준을 먼저 닫은 뒤에만 허용한다.
3. 실물 2대 FIELD는 2호기 확보 후 후속 ADR에서만 연다. 그 전까지 PARKED다.
4. 모든 단계의 증거는 수용 기준 §4 레코드 + `device-readback.sh --json` + 세션 로그로 남긴다. SSH 성공·HTTP 200만으로 GO 선언 금지.

**Consequences:** 순서 위반(예: stationary readback 없는 floor 주행, 실물 1대 없는 2대 FIELD 선언)은 이 ADR 위반이며 해당 gate는 HOLD로 되돌린다.

**Validation:**

```bash
sudo /opt/rosy/deploy/robot/verify/verify-pi.sh
sudo /opt/rosy/deploy/robot/verify/device-readback.sh --json
python3 -m pytest test/test_device_readback.py test/test_pinky_commissioning.py test/test_robot_runtime.py -q
```

**References:** D-46(readback), D-53(서명/readback 신뢰), D-58(readiness 게이트), D-54(Nav2 한계 fail-closed), G0–G5 커미셔닝 런북, `docs/deployment/pi5-acceptance-checklist.md` §§4–7, 수용 기준 §9.
