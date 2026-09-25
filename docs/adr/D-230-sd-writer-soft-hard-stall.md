## D-230 SD writer 멈춤은 두 단계로 다룬다 — soft 경고, hard 중단, CLI 진행률 우선

**Status:** Accepted (2026-09-25). `test_sd_writer_contract`·`test_sd_write_card_entrypoint`·`test_sd_personalization`·`test_media_readback` 245 passed.

**Context:**

1. 카드 쓰기 stall 감시는 프로세스 트리의 CPU+I/O 카운터(`Get-WriterSample`) 하나에만
   의존했다. xz 압축 해제와 USB 플러시 구간은 정상적으로 수 분간 0 CPU/0 I/O라서,
   일하는 writer를 죽이는 오살(false stall kill)이 나왔다. 반대로 죽은 writer를
   한 시간 방치한ことも 있다(release 005: Imager가 전 바이트를 쓰고 23분간 0 CPU/0 I/O로
   앉아 있었고 `-Wait`은 영원히 기다렸다).
2. Imager `--cli`는 진행률을 stdout에 찍는데 스크립트는 이를 버리고 있었다. 그래서
   카드 방향 실제 진행률 대신 WMI `Win32_Process` 전수 스캔이라는 무겁고 부정확한
   프록시에 의존했다.
3. 저속 미디어(`Type SLOW`)와 ERASE 확인(`Read-Host`)은 콘솔 입력이 없으면
   영원히 대기한다. `-Detach` 분리 윈도우·에이전트 실행에서는 이것이 멈춤으로 보인다.

**Decision:**

1. **writer stdout를 캡처해 파싱하고 진행 기준으로 승격한다.**
   `prepare-rosy-sd.ps1` 쓰기 감시는 Imager 프로세스를 `-RedirectStandardOutput`
   으로 띄우고 `%`·바이트 카운터 라인을 파싱해 `$written`에 반영한다. 파싱 결과가
   전진하면 WMI 카운터가 idle이어도 stall 시계를 리셋한다. 파서가 아무것도 못 읽는
   writer(구버전 Imager, fixture `.cmd`)에서는 기존 `Get-WriterSample` 폴백이 그대로
   동작한다.
2. **stall을 soft/hard 두 단계로 나눈다.**
   `-WriterSoftStallMinutes`(기본 2)는 경고만 낸다: `write` heartbeat 라인에
   `warning` 필드를 붙이며, stage 집계(`_stages`)는 바뀌지 않는다.
   `-WriterStallMinutes`(hard, 기본 5)에만 `taskkill /T /F`로 중단한다.
   soft는 hard 절반으로 clamp돼서, 짧은 테스트 타임아웃(`-WriterStallMinutes 0.05`)과
   작은 운영자 값도 기존과 동일하게 동작한다. kill 뒤의 card_state 판정
   (`writing` vs `written-unverified`, 99.9% resume band)과 readback 권위(D-187)는
   그대로다.
3. **`-NonInteractive`는 입력 대기를 fail-closed로 바꾼다.**
   저속 미디어와 ERASE 확인의 `Read-Host`는 `-NonInteractive`·입력 리다이렉트·미지정
   확인 값에서 묻지 않고 실패하며 다음 행동을 적는다. `write-card.ps1`이
   `-WriterSoftStallMinutes`·`-NonInteractive`를 그대로 전달한다.
4. **`card-write-status.ps1`이 soft 경고를 보여준다.**
   최근 heartbeat의 `warning` 필드를 `WARNING:` 줄과 JSON `warning` 필드로 노출한다.
   "느림"과 "멈춤"을 운영자가 구분할 수 있게 된다.

**Alternatives:**

- **WMI 폴링 간격만 늘리기**: 오살은 줄지만 정상 idle과 사망을 여전히 구분 못 한다.
  진행률 원천이 없어서 기각.
- **Imager 자체 verify 켜기**: 파이썬 전수 readback과 중복이라 총시간이 늘어난다.
  D-180 유지로 기각.
- **readback 재개형(오프셋 체크포인트)**: 유효하나 별도 변경이다. 이번 ADR 범위 밖,
  후속으로 둔다.

**Consequences:**

- 정상 idle writer를 죽이는 오살이 사라지고, 진짜 stall은 soft 경고로 먼저 보인다.
- 기존 계약 테스트의 kill 문구·card_state·재시도 안내는 그대로라 운영 런북 변경이 없다.
- 새 파라미터 2개가 `write-card.ps1` → `prepare-rosy-sd.ps1`으로 전달된다.
  기본값이라 기존 명령줄은 그대로 동작한다.

**Validation:**

1. `test/test_sd_writer_contract.py` 전수 통과 — stall kill 3종, 99.9% resume band,
   readback 권위, bundle/registry 무기록 포함.
2. `test/test_sd_write_card_entrypoint.py` 24 통과 — 파라미터 전달과 `-PrintArguments` 모양.
3. `test/test_sd_personalization.py`, `test/test_media_readback.py` 통과.

**References:** D-180(전체 readback 1회), D-187(writer 자기 실패 감지),
D-188(무인 운영·상태 명령·사전 속도 측정), D-225 3.2(99.9% resume),
`deploy/sd/prepare-rosy-sd.ps1`, `deploy/sd/write-card.ps1`,
`deploy/sd/card-write-status.ps1`, `deploy/sd/verify-media-readback.py`.
