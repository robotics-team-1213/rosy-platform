## D-182 SD 카드 쓰기는 전문가가 지켜보지 않아도 되게 한다: 분리 실행, 상태 명령, readback 멈춤 감시, 사전 속도 측정, 카드 신원

**Status:** Accepted (2026-09-24). [D-181](D-181-sd-writer-failure-handling.md)(실패 감지·카드 상태·resume)을 보강하고
D-181 리뷰 지적 일곱 건을 함께 반영한다. [D-180](D-180-sd-write-single-authoritative-verify.md)의 "readback 한 번이 권위 있는
검사"는 그대로다.

**Context:** 005 카드(32 GB, 리더기 시리얼 `000000000207`)의 실측이다.

- Imager 쓰기: 8,170 MB를 약 9 MB/s로 약 16분.
- 단일 스레드 readback: 카드 읽기와 xz 해제를 합쳐 약 3.4 MB/s로 약 60분. 그 뒤 00:09에 실패했고, 리더기가 `Get-Disk`에서
  사라졌다. 읽는 도중 연결이 끊긴 것으로 보인다. 그동안 아무것도 멈춤을 알리지 않았다.
- 앞 카드 004는 전체 48분이었다.
- 진행을 재는 도구가 없어서, 운영하던 에이전트가 완료 예상 시각을 여러 번 틀리게 말했다.

D-181 이후에도 사람 손에 남은 일이 있었다. 분리 실행 명령을 손으로 조립해야 했고, 진행 파일은 JSON을 직접 읽어야 했다.
readback 멈춤은 사람이 알아채야 했고, 같은 리더기에 꽂힌 다른 카드는 구분하지 못했다.

**Decision:**

1. **분리 실행이 운영자 기본값이다 (`write-card.ps1 -Detach`).** 관리자 권한 쓰기를 자기 창에서 띄운다. UAC는 한 번이고,
   창은 `-NoExit`로 결과를 보인 채 남는다. launcher는 기다리지 않고 바로 끝나며, 로그·진행 파일·`.exit` 표지·상태 명령
   경로를 출력한다. UAC로 띄운 창은 launcher의 job에 속하지 않으므로, 띄운 콘솔이나 에이전트 세션이 닫혀도 쓰기는 계속된다.
   launcher가 진행 파일을 먼저 만들고 `launch` 줄을 쓴다. `Start-Process -Verb RunAs`가 예외를 던지면(거부·시간 초과)
   `failed`/`untouched` 줄에 `next:`를 남기고 실패한다. 분리하지 않은 실행(`-Wait`)도 UAC 실패를 같은 방식으로 기록한다.
   UAC는 테스트에서 누를 수 없다. 그래서 `-ElevationLauncher <script>`라는 테스트 이음새로 launcher 논리를 검증한다.
2. **상태 명령 (`deploy/sd/card-write-status.ps1 -LogPath <log>`, `-Json`).** 진행 파일만 읽고 승격이 필요 없다. 출력 항목은 다음과 같다.
   - 현재 단계와 `card_state`, 처리한 바이트와 전체 바이트(비율).
   - 최근 heartbeat 최대 5구간의 실제 속도.
   - 이번 단계와 전체 작업의 ETA(남은 시간과 현지 시각). 쓰기 중에는 남은 쓰기에, 사전 측정 읽기 속도로 계산한 readback
     시간을 더한다.
   - 마지막 줄이 몇 초 전인지.
   - 끝났으면 결과와 `next:`.

   `write`·`readback`에서 바이트가 `-StallMinutes`(기본 5분) 넘게 늘지 않으면 `STALLED`를 표시한다. 다른 단계는 마지막 줄이
   그보다 오래되면 `STALLED`다. 단, `confirm` 단계와 사전 측정 뒤의 느린 매체 질문은 운영자 입력을 기다리는 중이므로
   `Waiting for:`로 표시한다. `launch` 뒤 창이 뜨지 않으면 UAC 창이 가려졌거나 거부된 것이라고 알린다.
   진행 파일은 로그 옆(plan 폴더)에 있다. 비관리자 launcher가 먼저 만들므로 운영자 소유이고, 관리자 창은 덧붙이기만 한다.
   접근이 거부되면 상태 명령이 그 이유를 말한다.
   실패 줄은 `next`와 (readback이면) `kind`를, 성공 `done` 줄은 `next`를 담는다.
3. **readback 멈춤 감시 (`-ReadbackStallMinutes`, 기본 5).** readback verifier를 `Start-Process`로 띄운다.
   stdout·stderr는 임시 파일로 받는다. 진행 파일에 새로 붙은 readback heartbeat의 `bytes`를 poll로 읽는다.
   - verifier의 heartbeat 간격은 `min(-HeartbeatSeconds, 한도/4)`다. 그래서 느려도 움직이는 readback은 한도 안에서 늘 바이트가 늘고,
     감시가 이를 멈춤으로 보지 않는다.
   - 한도 동안 바이트가 늘지 않으면 verifier 프로세스 트리를 끝내고 실패한다. 이때 `card_state=written-unverified`,
     `kind=io`, `next: … -ResumeAfterWrite`다.
   - verifier도 스스로 `--stall-seconds`(writer가 한도의 두 배로 넘김, 단독 실행 기본 600초)를 둔다. 장치 쪽 queue가 그 시간 동안
     비면 `kind: io`로 exit 3을 낸다. 막힌 읽기 스레드는 daemon이므로 기다리지 않고 `os._exit`로 끝낸다(리뷰 5). 두 감시를 모두 둔다.
4. **사전 속도 측정 (stage `preflight`, ERASE 확인 전).** `verify-media-readback.py --probe`는 네 가지를 한다.
   - xz index로 raw 크기를 읽는다(D-181의 `--raw-size` 호출을 대신한다).
   - 이미지 첫 섹터에서 MBR disk signature를 읽는다.
   - 대상 장치 앞 128 MiB(`-ProbeBytes`)를 읽기 전용으로 순서대로 읽어 시간을 잰다.
   - 장치의 MBR signature를 읽는다.

   장치를 못 읽어도 실패하지 않고 `device_error`로 알린다. 판정은 readback의 몫이다.
   예측 방법은 이렇다. 쓰기는 raw 크기 ÷ 가정 쓰기 속도이고, 가정 쓰기 속도의 기본은 측정 읽기 속도 × 0.8이다(`-AssumedWriteMBps`로 덮어쓴다).
   readback은 raw 크기 ÷ 측정 읽기 속도다. 측정하지 못했으면 005 값(쓰기 9, readback 3.4 MB/s)을 쓴다. MB는 10^6바이트다.
   결과는 콘솔(`Pre-flight: …`), 진행 파일 `preflight`/`measured` 줄, receipt `preflight`에 남는다.
   측정 읽기 속도가 `-MinReadMBps`(기본 10) 미만이면 `SLOW MEDIA` 경고와 함께 다른 포트·리더기, USB 3.0 리더기와 A1/A2 또는
   U3 카드를 권한다. 비대화형 실행(`-Confirmation`을 넘겼거나 입력이 리다이렉트됨)은 `-AcceptSlowMedia` 없이는 `untouched`로
   멈춘다. 대화형이면 `SLOW`를 입력해야 진행한다.
   `-PlanOnly`는 측정하지 않는다. `\\.\PhysicalDriveN`을 열려면 승격이 필요한데, plan은 승격하지 않는다.
   측정은 쓰기(이미 승격됨)의 확인 문구 직전에 한다.
5. **리더기가 아니라 카드의 신원 (리뷰 LOW).** plan에 `Get-Disk`의 `Signature`(8자리 hex)와 `Guid`를 `disk_signature`,
   `disk_guid`로 남긴다(크기는 원래 `disk_size`에 있다). 쓰기에서는 사전 측정 직후와, 실제 디스크일 때 ERASE 확인 뒤
   세 번째 프로브에서 plan 값과 비교한다. 장치 첫 섹터에서 읽은 signature가 있으면 `Get-Disk` 캐시보다 그 값을 믿는다.
   - 다르면 `a different card is in the reader`로 멈추고, `card_state=untouched`와 `next:`(plan의 카드를 다시 꽂거나 새 plan)를 남긴다.
   - 공장 초기 상태 카드라 signature와 GUID가 모두 없으면 시리얼과 크기로만 확인하고 경고한다.
   - 카드가 이미 이 릴리스의 MBR signature를 가지면, 이 plan의 앞선 시도가 파티션 표까지 쓴 경우에만 받아들이고 경고한다(결정 8).
   - `-ResumeAfterWrite`에서는 쓰기 뒤 signature가 바뀌는 것이 정상이다. 그래서 plan 대신 장치 MBR signature가 이미지의 것과
     같은지 본다. 다르면 readback 한 시간을 쓰기 전에 `card_state=unknown`으로 멈춘다. 이미지에 signature가 없거나 장치 첫 섹터를
     못 읽으면 경고하고 readback에 맡긴다.
   - D-182 이전 plan에는 이 필드가 없다. 그런 plan은 경고만 한다.
6. **boot 파티션의 파일 밖 영역을 byte 단위로 비교 (리뷰 MEDIUM-2).** Windows가 boot 파티션을 건드려 파일 단위 비교로
   넘어가도 다음 세 곳은 byte 단위로 비교한다.
   - 카드의 backup boot sector(BPB `0x32`)와 primary.
   - reserved 영역과 이미지. FSInfo 섹터(BPB `0x30`)의 free count(488–491)와 next free(492–495)만 뺀다.
   - FAT copy 2 이후와 카드의 FAT copy 1. FAT[1]의 clean-shutdown(`0x08000000`)과 hard-error(`0x04000000`) 비트만 뺀다.

   FAT 1은 이미지와 비교하지 않는다. Windows가 `System Volume Information`에 cluster를 할당하기 때문이다.
   허용 목록은 `FSINFO_TOLERATED`, `FAT1_STATUS_BITS` 상수로 코드에 드러나 있다. 증거 `boot_partition.non_file_areas`에는
   비교한 바이트 수, backup boot sector 위치, 허용 필드 목록, 실제로 달랐던 허용 필드가 남는다. backup FSInfo(보통 섹터 7)는
   허용하지 않는다. 실제 카드에서 Windows가 그것도 바꾸면 목록에 명시적으로 더한다.
7. **D-181 리뷰 반영.**
   - (MEDIUM) `-ReadbackDevice`는 fixture 전용이다. `-DiskInventoryJson` 없이 쓰면 resume 여부와 관계없이 거부한다.
     receipt에 `readback_target`을 남긴다.
   - (MEDIUM) Imager 멈춤 감시는 `Win32_Process`를 `ParentProcessId`로 따라가 프로세스 트리 전체의 CPU·I/O를 합산한다.
     부모보다 늦게 생긴 PID만 자식으로 본다(PID 재사용 방지). 실제 디스크에서는 `.exe`가 아닌 `-RpiImager`를 거부한다.
     fixture 모드는 `.cmd` 가짜 writer를 계속 쓴다.
   - (LOW) `taskkill`은 함수 안에서 `ErrorActionPreference Continue`와 `*> $null`로 부른다. 그 뒤 `WaitForExit(10000)`의
     결과를 확인한다.
   - (LOW) Imager를 끝내지 못하면 `card_state=writing`으로 실패한다. `next:`는 "리더기를 뽑고 PC를 재부팅한 뒤 전체 쓰기(resume 아님)"다.
   - (LOW) verifier의 `queue.get()`에 시간 제한을 두고, 멈춘 쪽의 `join()`은 기다리지 않는다(결정 3).
   - (LOW) heartbeat 쓰기의 `OSError`는 stderr에 한 줄 남기고 계속한다. 좋은 카드를 `kind: image`로 떨어뜨리지 않는다.
   - (LOW) boot 파티션에 첫 byte를 쓰기 직전에 stage `bundle-writing`, `card_state=bundle-partial`를 기록한다.
     그 뒤 실패하면 `next:`는 전체 재기록이다. `-ResumeAfterWrite`는 boot 파티션에 `rosy-provision/`이 이미 있으면 readback 전에 거부한다.

8. **D-182 리뷰 반영.**
   - (MEDIUM) 카드가 이 릴리스의 MBR signature를 가질 때는 두 조건을 모두 만족해야 받아들인다. 첫째, boot 파티션에
     `rosy-provision/`이 없어야 한다. 둘째, 같은 plan(첫 진행 줄의 `plan` 필드)으로 Imager 쓰기를 시작한 이전 시도의 진행 파일이
     plan·로그 폴더에 있어야 한다. 그렇지 않으면 "different card"로 `untouched` 멈춤이다. 이렇게 하면 로봇 A용으로 다 쓰고 아직
     부팅하지 않은 카드가, 빈 카드로 만든 plan B에서 지워지지 않는다.
   - (MEDIUM) fixture 모드는 fixture 대상에만 묶는다. `-DiskInventoryJson`이 있으면 `.exe` writer를 거부한다(`-PlanOnly` 제외).
     `-ReadbackDevice`는 `\\.\`, `\\?\` 장치 경로를 거부한다(`\\.\pipe\` stand-in만 허용). fixture receipt에는 `fixture: true`를 남긴다.
   - (MEDIUM) `write-card.ps1`은 `-LogPath`와 `-RpiImager`를 이 콘솔 위치 기준 절대 경로로 바꾼다. `-PythonExe`는 경로 구분자가
     있을 때만 바꾸고, 이름만 주면 PATH에서 찾는다. 관리자 창은 `C:\Windows\System32`에서 시작하므로, 상대 경로를 그대로 두면
     진행 파일이 둘로 갈리고 `.exit` 표지를 잃는다. `[IO.Path]::GetFullPath`는 PowerShell 위치를 따르지 않아 쓰지 않는다.
   - (LOW) readback 감시는 새 heartbeat가 없을 때 verifier 프로세스 트리의 `ReadTransferCount`도 본다. 늘었으면 진행으로 본다.
     heartbeat 파일이 잠기거나 디스크가 차도 정상 readback을 죽이지 않는다.
   - (LOW) probe는 `device_mbr_read`를 알리고, MBR이 있으면 signature가 0이어도 `"00000000"`으로 보고한다. 섹터를 실제로 읽었으면
     "signature 없음"도 그대로 믿는다. ERASE 확인 뒤의 재확인도 `Get-Disk`만 보지 않고 카드 첫 섹터를 다시 읽는다(512바이트 probe).
   - verifier worker `close()`는 어느 경로에서든 `join(timeout)`이다. 불일치나 이미지 오류 뒤 막힌 장치 스레드가 판정을 `io`로 바꾸지 않는다.
   - probe가 `-ProbeSeconds`(기본 120) 안에 끝나지 않으면 그때까지 읽은 양으로 속도를 낸다(0일 수도 있다). 그래서 느린 매체 관문을
     건너뛰지 않고 `-AcceptSlowMedia`를 요구한다.

진행 파일 단계는 `launch` → `verify-signature` → `select-disk` → `preflight` → `confirm` → `write` → `readback` → `bundle` →
`bundle-writing` → `receipt` → `done`(실패는 `failed`)이다. `card_state`에는 `bundle-partial`이 더해진다.

**실패 유형표 (D-181 표에 더하거나 바꾸는 행):**

| 실패 | 감지 | 도구 자동 동작 | 카드 상태 | 운영자 다음 행동 |
|---|---|---|---|---|
| UAC 거부·시간 초과 | `Start-Process -Verb RunAs` 예외 | 진행 파일에 `failed`와 `next` 기록 | `untouched` | 다시 실행하고 UAC 승인 |
| 같은 리더기에 다른 카드 | plan `disk_signature`·`disk_guid` ≠ 장치 첫 섹터 또는 `Get-Disk` | 확인 문구 전(과 ERASE 직전)에 멈춤 | `untouched` | plan의 카드를 다시 꽂거나 이 카드로 새 plan |
| 공장 초기 카드(신원 없음) | signature·GUID 모두 없음 | 경고 후 진행(시리얼+크기) | `untouched` | 카드 라벨 확인 |
| 느린 매체 | 사전 측정 < `-MinReadMBps` | 경고. 비대화형이면 멈춤 | `untouched` | 다른 포트·USB 3.0 리더기·A1/A2·U3 카드, 또는 `-AcceptSlowMedia` |
| Imager 멈춤 후 끝내지 못함 | `WaitForExit(10000)` 거짓 | 멈춤 | `writing` | 리더기를 뽑고 PC 재부팅 뒤 전체 쓰기(resume 금지) |
| readback 멈춤(바이트 불변) | 진행 파일 heartbeat `bytes`가 `-ReadbackStallMinutes` 동안 그대로 | verifier 트리 종료, `kind io` | `written-unverified` | 다시 꽂거나 다른 리더기로 `-ResumeAfterWrite` |
| verifier 안에서 장치 읽기가 막힘 | 장치 queue가 `--stall-seconds` 동안 빔 | exit 3, `kind: io` | `written-unverified` | 위와 같음 |
| resume인데 카드가 이 이미지가 아님 | 장치 MBR signature ≠ 이미지 MBR signature | readback 전에 멈춤 | `unknown` | 쓴 카드인지 확인, 맞으면 전체 쓰기 |
| resume인데 bundle이 이미 있음 | boot 파티션 `rosy-provision/` 존재 | readback 전에 멈춤 | `bundle-partial` | 전체 재기록(registry에 이 장치가 있으면 먼저 정리) |
| bundle 복사 중 실패(카드 뽑힘 등) | `Fail`·`trap`, stage `bundle-writing` | 멈춤 | `bundle-partial` | 전체 재기록. resume는 불가 |
| 이 릴리스를 가진 카드인데 bundle이 있음 | 장치 MBR signature = 이미지 + boot `rosy-provision/` | ERASE 전 멈춤 | `untouched` | 다른 로봇용으로 끝난 카드다. plan의 카드를 꽂는다 |
| 이 릴리스를 가진 카드인데 이 plan의 이전 쓰기 기록 없음 | 같은 `plan`의 진행 파일에 `write`/`writing` 없음 | ERASE 전 멈춤 | `untouched` | plan의 카드를 꽂거나 이 카드로 새 plan |
| probe가 제한 시간 안에 끝나지 않음 | `-ProbeSeconds` 초과, 읽은 양으로 속도 계산 | 느린 매체로 취급 | `untouched` | 다른 리더기·포트, 또는 `-AcceptSlowMedia` |
| boot 파티션 파일 밖 영역 차이 | reserved·FAT 2·backup boot sector 비교 | readback 불일치로 멈춤 | `written-unverified` | 전체 쓰기, 반복되면 카드 교체 |

**D-181 "여전히 사람이 해야 하는 일"에서 닫는 것:**

- 닫음: "readback은 heartbeat만 남기고 멈춤 감시는 없다" → 결정 3.
- 닫음: "같은 리더기에 꽂힌 같은 용량의 다른 카드는 구분하지 못한다" → 결정 5(신원 없는 공장 초기 카드끼리는 여전히 구분 못 한다).
- 줄임: "UAC 예를 누른다. 거부되면 도구는 알리기만 한다" → 누르는 일은 남는다. 거부는 진행 파일과 상태 명령에 남는다.
- 줄임: "세션 종료와 정전은 사람이 진행 파일 마지막 줄을 읽고 고른다" → 분리 실행은 세션 종료를 견딘다. 상태 명령이 마지막 줄을
  해석해 `next:`를 말한다. 정전은 여전히 사람이 명령을 고른다.
- 그대로: bundle 뒤 registry·receipt 쓰기 실패의 registry 수동 정리.

**Alternatives:**

- 상태를 Windows 알림이나 웹 대시보드로 보이기 — 에이전트가 읽기 어렵다. 파일 하나와 `-Json`이면 사람과 에이전트가 같은 답을 본다.
- PlanOnly에서 속도 측정 — plan 단계를 승격시켜야 한다. 쓰기는 어차피 승격하므로 확인 문구 직전이 공짜 자리다.
- 카드 신원으로 CID 레지스터 사용 — USB 리더기는 SD CID를 넘기지 않는다. MBR signature와 GPT GUID는 `Get-Disk`로 비승격 plan에서도 보인다.
- readback 감시를 verifier 안에만 두기 — verifier가 끝내 응답하지 않으면(드라이버에서 멈춘 읽기) 밖에서 끝낼 사람이 없다. 두 겹으로 둔다.

**Consequences:** 운영자는 `-Detach`로 띄우고 상태 명령만 본다. 멈춘 readback은 최대 5분 뒤 `kind io` 실패와 resume 명령으로 바뀐다.
ETA는 실제 heartbeat 바이트와 같은 카드의 사전 측정에서 나온다. 추측한 시각을 말하지 않는다. 느린 카드·리더기는 쓰기 전에 드러난다.
같은 리더기에 꽂힌 다른 카드는 ERASE 전에 멈춘다. 사전 측정은 카드 앞 128 MiB를 한 번 더 읽는다(10 MB/s에서 약 13초).

**Validation / Transition:** 테스트는 다음을 고정한다.
- `test/test_sd_writer_contract.py`:
  - named pipe로 만든 가짜 카드(`test/sd_pipe_card.py`)로, 매달린 readback은 멈추고 `kind io`·`written-unverified`·resume을
    말하는지, 4 MiB를 0.8초 간격으로 내주는 느린 readback은 한도(3초)보다 오래 걸려도 끝까지 가는지.
  - 자식 프로세스가 I/O를 하는 가짜 writer가 죽지 않는지.
  - 사전 측정 줄과 예측값, `-MinReadMBps` 경고와 `-AcceptSlowMedia`.
  - plan의 카드 신원, 다른 signature의 카드가 확인 문구 전에 멈추는지, 공장 초기 카드 경고.
  - resume에서 이미지 MBR signature 불일치 거부, 이미 있는 bundle 거부, `bundle-writing` 실패의 전체 재기록 안내.
  - 실제 디스크에서 `-ReadbackDevice`와 `.exe` 아닌 writer 거부.
- `test/test_sd_write_card_entrypoint.py`: `-Detach`가 기다리지 않고 경로를 출력하는지, UAC 거부의 진행 파일 기록.
  상태 명령의 진행 중·쓰기 중·멈춤·실패·완료·확인 대기·UAC 대기·파일 없음(텍스트와 JSON).
- `test/test_media_readback.py`: reserved 영역·FSInfo 서명·backup boot sector·FAT 2·FAT[1] 하위 비트의 1 byte 반전이 실패하고
  Windows 필드는 허용되는지, probe, verifier 안의 멈춤 exit 3, 느린 카드, 쓸 수 없는 진행 파일.

실제 카드로 확인할 것은 다음이다.
- 실제 UAC 창 하나와, 띄운 콘솔을 닫은 뒤에도 창이 살아 있는지.
- `-NoExit` 창에 결과가 남는지.
- `\\.\PhysicalDriveN` 128 MiB 측정값이 실제 쓰기·readback 시간을 얼마나 맞히는지.
- 실제 카드에서 `Get-Disk` `Signature`와 첫 섹터 값이 같은지.
- Windows가 backup FSInfo나 다른 FAT[1] 비트를 바꾸는지.
- 리더기를 뽑았을 때 멈춤 감시가 5분 안에 끝나는지.
- Imager가 자식 프로세스로 쓰는지.
