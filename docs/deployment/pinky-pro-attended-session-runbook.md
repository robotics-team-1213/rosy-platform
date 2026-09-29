# Pinky Pro 입회 세션 런북 — 측정 · 커미션 · G4 (2026-09-30)

**대상:** 로봇 옆에 사람이 있는 물리 세션. 이 문서는 순서·명령·판정·중단 조건을 하나로 묶는 운영 지침이다.
**근거:** D-347(측정 기준선 §5), D-319(커미션 도우미), D-311/D-312/D-314(G4 계단), D-321(입회 보정·매핑 승인), D-192(부팅 토크 오프).

## 0. 전제 확인 (전원 켠 직후, 전부 읽기 전용)

```bash
ssh <alias> 'uptime; systemctl is-active rosy-core rosy-io rosy-camera rosy-navigation; \
  grep -E "ROSY_RUNTIME_MODE|ROSY_NAVIGATION_BACKEND|ROSY_IO_DRIVE" /etc/rosy/runtime.env; \
  ls /etc/rosy/approvals/ 2>/dev/null'
```

확인할 것: ①로봇이 예상한 release(`cat /opt/rosy/current/RELEASE_ID`) ②현재 모드가 기대 상태(보통 `core`+`drive=false`) ③승인 파일 현황 ④**독립 전원 차단 수단이 손에 닿는가** — 이게 없으면 아래 2·3단계를 시작하지 않는다.

## 1. 상주 CPU 측정 (B레인 관문)

```bash
# 스크립트가 디바이스에 없으면(오늘 이전 release):
scp deploy/robot/pinky_pro/verify/measure-resident-cpu.sh <alias>:/tmp/
ssh <alias> 'chmod +x /tmp/measure-resident-cpu.sh'

# ① 현 상태 그대로
ssh <alias> 'sudo /tmp/measure-resident-cpu.sh 60'

# ② 카메라 A/B (단위를 멈추고 되살린다 — 도구가 보장)
ssh <alias> 'sudo /tmp/measure-resident-cpu.sh --ab-unit rosy-camera.service 120'

# ③ navigation/SLAM 백엔드 A/B — 승인된 navigation이 떠 있을 때만
ssh <alias> 'sudo /tmp/measure-resident-cpu.sh --ab-unit rosy-navigation.service 120'
```

- **판정**: 낭비 입증 = A/B 두 표의 차가 부하 문맥에서 재현된다. 기준은 `docs/plans/2026-09-29-on-demand-activation-measurement-baseline.md` §5 (부하 25 이상 실행은 무효 — R4 준용).
- **증거**: `/var/lib/rosy/resident-cpu-*.md`를 세션 뒤 회수해 세션 기록에 첨부.
- 보너스: 2단계(커미션) 뒤 `motor` 모드에서 ①을 한 번 더 — 모드별 상주 프로파일 비교 데이터.

## 2. 커미션 도우미 (D-319, 승인됨)

```powershell
# ① 먼저 무동작 확인 (ID·상태만 읽는다)
deploy\robot\pinky_pro\sd\enable-motor-commissioning.ps1 -DeviceName <rosy-pinky-XXXX> -CheckOnly
# ② 입회 전제를 소리내 확인한 뒤 본 실행
deploy\robot\pinky_pro\sd\enable-motor-commissioning.ps1 -DeviceName <rosy-pinky-XXXX>
```

- 도우미가 하는 일/하지 않는 일: 표시된 E-Stop 유지, 토크 오프 ID 탐색, `motor`+`drive=true` 원자 전환, `drive=ready`·단일 `cmd_vel` 발행자 판독. **무인 토크·G4 승인 파일 생성·내비게이션 승격은 없다.**
- **이상 시 복구**(D-319 본문): I/O 정지 → 저장된 `runtime.env` 복원 → CORE 재시작 → E-Stop 재걸기 → 무구동 I/O 기동 → 토크 레지스터 2개 판독.
- **증거**: 기기별 판독은 `X:\DevTemp` 개인 운영 기록에.

## 3. G4 계단 (D-311/312/314 · D-321 승인 흐름)

순서가 계약이다: **실측 방향 시도 → 제한 이동량 정지 시험 → (매핑이 필요하면) 승인 뒤 지도 생성**.

- 실측 G4는 명령 수락이 아니라 **물리 측정**이다: 요청 속도 상한(예: 0.03 m/s) 대비 실측 피크, 정지 거리·시간을 기록한다. D-319 세션의 교훈 — "두 번째 시도의 피크가 요청 상한을 초과했고, 그것은 G4 통과가 아니다."
- 지면 G4는 제한된 이동량으로 간소화한다(D-314). 수동 운전의 반복 확인 요구는 없다.
- **지도 생성은 승인 뒤에만 시작**(D-321): `mapping_approval.py` 절차 준수.
- **G4 증거 오남용 금지**: API 명령 수락만으로 G4 승인 마커를 만들지 않는다(D-319 본문).

## 4. 세션 마감

1. 기록 회수: `resident-cpu-*.md`, 커미션 판독, G4 측정값.
2. 로봇 상태 복원 확인: `core` 모드, E-Stop 걸림, 토크 레지스터 2개 모두 disabled 판독.
3. 게이트 갱신: 측정 결과 → B레인 관문 판정 회차로, G4 통과분 → 해당 모듈 `progress.md` DEVICE 게이트로.
4. 사고·이상 반응은 세션 중 즉시 저널로.

## 중단 조건 (전 구간 공통)

- 부하 25 이상·OS 스케줄링 공백 관찰 → 측정 무효 처리 후 재시도(R4 준용).
- 예상 밖 움직임·판독 불일치 → 즉시 전원 차단 → 2단계 복구 절차 → 세션 중단 기록.
- 입회자가 자리를 뜨면 측정 외的一切 진행 금지.
