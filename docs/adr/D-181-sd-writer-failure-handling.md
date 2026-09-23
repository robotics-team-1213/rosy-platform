## D-181 SD 카드 writer는 자기 실패를 감지해 안전하게 멈추고, 카드 상태와 다음 행동을 알린다

**Status:** Accepted (2026-09-23). [D-180](D-180-sd-write-single-authoritative-verify.md)(readback 한 번으로 검증)과
[D-173](D-173-first-pinky-card-from-merged-release.md)(검토된 plan에 고정한 기록)의 WRITE 단계를 보강한다.
근거 사례는 [long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md](../solutions/workflow-issues/long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md)다.

**Context:** 릴리스 `2026.09.23-005`를 32 GB 카드 한 장에 쓰는 데 약 3시간 30분이 걸렸다. 쓰기 자체보다
실패를 알아차리고 복구하는 데 시간이 들었다.

- ERASE 확인 문구가 맞지 않았다. 무엇을 입력했는지는 어디에도 남지 않았다.
- 에이전트 세션이 끝나자 관리자 쓰기가 receipt와 `.exit` 표지 없이 사라졌다.
- 분리해 띄운 launcher가 로그 없이 끝났다. UAC 승인이 거부됐거나 시간이 지난 것으로 보인다.
- `rpi-imager --cli`가 8,170 MB를 모두 쓴 뒤 CPU·I/O 0으로 23분간 멈췄다. `Start-Process -Wait`는 계속 기다렸다.
- transcript는 한 시간 동안 머리글만 있었다. 어느 단계인지 아무도 몰랐다.
- 실패할 때마다 처음부터 다시 썼다. 이미 끝까지 써진 카드도 약 20분짜리 쓰기를 다시 했다.

`Get-Disk`의 빈 `SerialNumber`는 USBSTOR fallback으로 이미 고쳤다(`fix/sd-usb-instance-serial`).

**Decision:**

1. **진행 파일.** `write-card.ps1`은 로그 옆 `<LogPath>.progress.jsonl` 경로를 `prepare-rosy-sd.ps1 -ProgressPath`로
   넘긴다(단독 실행이면 `<ReceiptPath>.progress.jsonl`). 단계가 바뀔 때마다 JSON 한 줄을 덧붙이고 바로 flush한다
   (`Start-Transcript` 버퍼에 기대지 않는다). 각 줄은 `ts`(UTC ISO), `stage`, `card_state`, 선택 `detail`을 가진다.
   - `stage`: `verify-signature`, `select-disk`, `confirm`, `write`, `readback`, `bundle`, `receipt`, `done`, `failed`
   - `card_state`: `untouched`, `writing`, `written-unverified`, `verified-no-bundle`, `complete`, `unknown`
   - `write` 중에는 약 60초(`-HeartbeatSeconds`)마다 Imager의 `Win32_Process.WriteTransferCount`를 `bytes`로 남긴다.
     `readback` 중에는 `verify-media-readback.py --progress`가 같은 파일에 비교한 바이트 수를 남긴다.
   - 비관리자 쪽 `write-card.ps1`은 로그와 진행 파일 경로를 먼저 출력한다.
2. **Imager 멈춤 감시.** `Start-Process -Wait` 대신 poll loop로 기다린다. CPU 시간(kernel+user)과 I/O 전송량
   (read·write·other)이 `-WriterStallMinutes`(기본 5분) 동안 모두 그대로면 멈춤으로 본다. 멈추면 Imager 프로세스
   트리를 끝내고 실패한다. 쓴 바이트가 raw 이미지 크기에 닿았으면 `written-unverified`, 아니면 `writing`이다.
   raw 크기는 압축을 풀지 않고 xz stream index에서 읽는다(`verify-media-readback.py --raw-size`). Imager 종료 코드 검사는 그대로 둔다.
3. **실패 문구에 단계·카드 상태·다음 행동.** 서명 검증부터 모든 실패는 `stage=… card_state=…`와 한 줄짜리
   `next: …`를 붙이고 진행 파일에 `failed` 줄을 남긴다. `Fail`을 거치지 않은 예외(도구 없음, 복사 실패)도 script
   `trap`이 같은 형식으로 바꾼다. 확인 문구가 틀리면 입력한 값을 따로 보여 준다(끝의 `:` 같은 실수가 보이도록).
4. **`-ResumeAfterWrite`.** 두 스크립트에 둔다. Imager만 건너뛰고 전체 readback → bundle → registry → receipt를
   평소와 똑같이 돈다. readback이 권위 있는 검사이므로(D-180), 카드가 서명된 이미지와 byte 단위로 같고 boot
   파티션이 파일 단위로 같으면 어떻게 써졌는지는 상관없다. 서명 검증, 시리얼 선택, fingerprint 재확인, plan
   대조, ERASE 확인은 모두 그대로 요구한다. plan의 receipt가 이미 있으면 평소처럼 거부한다. receipt에
   `resumed_after_write: true`를 남기고 `writer_exit_code`는 `null`이다. 재프로비저닝 검사는 `resumed_after_write: true`인
   receipt의 `null` 종료 코드만 받아들인다(readback `verified: true`는 여전히 필수).
5. **쓴 파일을 서명된 해시에 묶는다 (리뷰 MEDIUM-1).** `verify-media-readback.py`의 `verify()`는 `lzma.open`에
   넘기는 압축 파일 객체를 SHA-256 reader로 감싸고, 끝나면 xz stream 뒤의 나머지까지 읽어 파일 전체의
   `image_sha256`을 낸다. `prepare-rosy-sd.ps1`은 이 값이 서명 검증 때의 `$actualHash`와 다르면 실패한다. 추가 패스는 없다.
6. **bundle 직전 디스크 재선택 (리뷰 노트).** boot mount를 찾기 직전에 시리얼로 디스크를 다시 찾고
   `Select-SafeDisk`와 fingerprint를 계획된 디스크와 비교한다. 다르면 `-ResumeAfterWrite` 안내와 함께 멈춘다.
7. **긴 쓰기는 분리해 띄운다.** 에이전트나 짧게 사는 셸의 자식으로 띄우지 않는다. 운영자가
   `Start-Process powershell -Verb RunAs -ArgumentList … -NoExit -File write-card.ps1 … -LogPath <log>`로 관리자 창을
   하나 띄우면, 그 창은 이미 관리자라 `write-card.ps1`이 다시 승격하지 않는다(UAC 한 번). transcript와 진행 파일은
   그 창이 직접 쓴다. 절차는 [runbook](../deployment/pinky-pro-first-device-runbook.md) "카드 쓰기 중 문제가 생겼을 때"에 있다.
8. **readback은 압축 해제와 카드 읽기를 겹친다.** 005 readback은 두 일을 번갈아 해 약 3.4 MB/s였다. 이제 스레드 하나가
   4 MiB씩 압축을 풀고, 다른 하나가 카드를 순서대로 4 MiB씩 읽어 각자 크기 4의 queue에 넣는다. 주 스레드는 비교와
   raw·device 해시를 맡는다(압축 스트림 해시는 lzma가 바이트를 소비하는 압축 해제 스레드에서 갱신된다). 판정·오류 문구·JSON
   필드는 그대로이고, 어느 worker의 예외도 그대로 실패로 올라온다(부분 통과 없음). 모든 경로에서 두 스레드를 join한다.
   이미지 끝 뒤를 미리 읽다 난 오류는 판정에 넣지 않는다(예전에도 그 영역은 읽지 않았다). 256 MiB 로컬 fixture에서
   page cache 파일은 3.10초 → 2.34초, 60 MB/s로 늦춘 장치는 11.55초 → 6.81초였다. 8 MiB 장치 읽기는 이득이 없어 4 MiB로 둔다.

**실패 유형표:**

| 실패 | 감지 | 도구 자동 동작 | 카드 상태 | 운영자 다음 행동 |
|---|---|---|---|---|
| 압축 이미지 해시·서명 불일치 | `Get-FileHash`, `verify-image-release.py` 비0 | 디스크 탐색 전 멈춤, `failed` 기록 | `untouched` | 릴리스(이미지, `SHA256SUMS`, `.sig`)를 다시 받고 재실행 |
| ERASE 확인 문구 불일치 | 문구 대소문자 구분 비교 | 쓰기 전 멈춤, 입력값 표시 | `untouched` | 같은 명령 재실행, 표시된 문구를 정확히 입력(또는 `-Confirmation`) |
| 카드를 못 찾음·같은 시리얼 둘 이상·안전 조건 위반 | `Resolve-DiskNumberBySerial`, `Select-SafeDisk` | 쓰기 전 멈춤 | `untouched` | 리더기를 다시 꽂고 `-PlanOnly`로 어떤 디스크가 잡히는지 본 뒤 재실행 |
| 프로브 사이 또는 쓰기 직전 디스크 변경 | fingerprint 비교(두 번째·세 번째 프로브) | 쓰기 전 멈춤 | `untouched` | 위와 같음 |
| 잘못된 카드를 꽂음 | 다른 리더기면 시리얼 불일치, 같은 리더기면 plan의 `disk_size`·`disk_model` 대조 | 쓰기 전 멈춤 | `untouched` | 맞는 카드로 바꾸고 재실행. 같은 리더기·같은 용량의 다른 카드는 **구분하지 못한다**(수동) |
| UAC 거부·시간 초과 | `Start-Process -Verb RunAs` 예외 | 비관리자 쪽이 `card_state=untouched`와 함께 실패 | `untouched` | 재실행 후 UAC 승인, 또는 분리 실행 |
| 띄운 세션이 끝남 | 도구는 감지 못함. `.exit` 표지 없음 + 진행 파일 마지막 줄 | 비관리자 쪽이 살아 있으면 마지막 `stage`·`card_state` 보고 | 진행 파일 마지막 줄 | 마지막 줄의 `card_state`대로(아래 세 행). 예방: 분리 실행 |
| Imager 비0 종료 | 종료 코드 | 멈춤 | `writing`(일부 기록) | 전체 쓰기 재실행 |
| Imager 멈춤, 전체 크기 전 | CPU·I/O 카운터가 `-WriterStallMinutes` 동안 불변 | Imager 프로세스 트리 종료 후 멈춤 | `writing` | 전체 쓰기 재실행 |
| Imager 멈춤, 전체 크기 뒤 | 위 + `WriteTransferCount` ≥ xz index raw 크기 | Imager 종료 후 멈춤 | `written-unverified` | `-ResumeAfterWrite` |
| readback 불일치(짧은 매체, byte 차이, boot 파일 차이) | `verify-media-readback.py` exit 1 | bundle·receipt·registry 전 멈춤 | `written-unverified`(틀림 확인) | 전체 쓰기 재실행, 반복되면 카드 교체 |
| readback 중 카드 빠짐·I/O 오류 | exit 3(`DeviceReadError`) | 멈춤 | `written-unverified` | 카드를 다시 꽂고 `-ResumeAfterWrite` |
| 서명 뒤 이미지 파일이 바뀜 | readback `image_sha256` ≠ 서명된 해시 | 멈춤 | `unknown` | 릴리스를 다시 받고 전체 쓰기 |
| readback 증거 형식 오류 | 64자리 hex·양수 `bytes_verified` 검사 | 멈춤 | `written-unverified` | `-ResumeAfterWrite` |
| bundle 직전 디스크가 바뀜 | 시리얼 재해석 + `Select-SafeDisk` + fingerprint | 멈춤 | `verified-no-bundle` | 리더기·카드를 확인하고 `-ResumeAfterWrite` |
| bundle 단계의 기타 실패(boot 파티션 없음, 복사 실패) | `Fail` 또는 `trap` | 멈춤 | `verified-no-bundle` | `-ResumeAfterWrite` |
| bundle을 올린 뒤 registry·receipt 쓰기 실패 | `trap` | 멈춤 | `complete`(receipt 없음) | 수동: registry에 이 신원이 들어갔는지 확인해 되돌린 뒤 전체 쓰기. readback이 bundle을 추가 파일로 보므로 resume은 거부된다 |
| 정전·PC 꺼짐 | 도구는 감지 못함. 진행 파일 마지막 줄(줄마다 flush) | 없음 | 진행 파일 마지막 줄 | `written-unverified`·`verified-no-bundle`면 `-ResumeAfterWrite`, `writing`이나 모르면 전체 쓰기 |
| plan의 receipt가 이미 있음 | `Test-Path` | 즉시 멈춤(resume 포함) | 이전 기록 완료 | 다른 카드라면 새 plan(`-PlanOnly`) |

resume을 잘못 골라도 안전하다. readback이 불일치를 잡고 bundle 전에 멈추므로, 비용은 readback 한 번(약 8분)이다.

**여전히 사람이 해야 하는 일:**

- UAC "예"를 누른다. 거부되면 도구는 알리기만 한다.
- 세션 종료와 정전은 도구가 스스로 감지하지 못한다. 사람이 진행 파일 마지막 줄을 읽고 명령을 고른다.
  resume을 자동으로 이어 붙이지 않는다.
- readback은 heartbeat만 남기고 멈춤 감시는 없다. heartbeat가 5분 넘게 늘지 않으면 사람이 창을 닫고 표대로 한다.
- 시리얼은 카드가 아니라 리더기를 가리킨다. 같은 리더기에 꽂힌 같은 용량의 다른 카드는 구분하지 못한다.
  ERASE 문구를 입력하기 전에 카드 라벨을 확인한다.
- bundle을 올린 뒤 registry·receipt 쓰기가 실패하면 registry를 손으로 정리한다.

**Alternatives:**

- 멈춤을 감지하면 자동으로 resume — 멈춘 원인(리더기, 드라이버)이 그대로일 수 있고, 운영자가 모르는 사이
  카드가 두 번 다뤄진다. 명령 한 줄을 알려 주는 것으로 충분하다.
- readback을 중단 지점부터 이어 하기 — 오프셋 상태를 저장해야 하고, 중간에 카드가 바뀌었는지 다시 증명해야 한다.
  전체 readback 한 번이 더 단순하고 권위도 유지된다.
- Imager 대신 자체 raw writer — 쓰기 속도·진행 신호를 직접 쥐지만, 관리자 raw 쓰기 코드를 새로 검증해야 한다.
  Imager가 또 멈추면 다시 검토한다.
- raw 크기를 릴리스 manifest에 넣기 — 서명 대상 형식이 바뀐다. xz index는 이미 서명된 파일 안에 있다.

**Consequences:** 끝까지 써진 카드가 멈추거나 readback 중 빠져도 약 20분짜리 쓰기를 다시 하지 않고 readback
한 번으로 끝낸다. 23분짜리 무신호 대기는 기본 5분 뒤 실패로 바뀐다. 모든 실패가 카드 상태와 다음 명령을
말하므로 에이전트나 운영자가 추측하지 않는다. 진행 파일은 줄마다 flush하므로 세션이 사라져도 어디까지 갔는지 남는다.

**Validation / Transition:** `test/test_sd_writer_contract.py`가 성공 시 단계 순서와 상태, 각 실패 유형(서명, 확인
문구, 디스크 없음, Imager 비0, 쓰기 중 멈춤, 마지막 byte 뒤 멈춤, readback 불일치, 읽을 수 없는 장치, 서명 뒤 바뀐
이미지, bundle 직전 디스크 변경)의 `stage`·`card_state`·`next:`를 고정한다. 멈춤은 가짜 writer(`cmd` + `ping`)와
`-WriterStallMinutes 0.05`로 재현한다. `-ResumeAfterWrite`가 writer를 부르지 않고, readback 불일치에서 멈추고, 기존
receipt와 틀린 확인 문구를 거부함을 확인한다. `test/test_media_readback.py`가 xz stream 뒤 byte까지 포함한
`image_sha256`, heartbeat, exit 3, xz index raw 크기를 확인한다. 실제 Imager의 멈춤 감지, 실제 카드에서의
`WriteTransferCount`와 raw 크기 비교, 카드를 뽑았을 때의 exit 3, 분리 실행의 UAC 한 번은 다음 실제 카드에서 확인한다.
