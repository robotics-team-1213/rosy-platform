## D-389 긴급 카드 쓰기는 전체 readback만 건너뛰고, 검증 안 됨을 모든 증거에 남긴다

**Status:** Accepted (2026-10-01, 사용자 요청). 브랜치 `fix/card-write-confirm-and-artifact-download`.
`test_sd_writer_contract`·`test_sd_write_card_entrypoint`·`test_media_readback` 통과, 새 게이트마다 변이 증명.
번호: D-382 → D-383 → D-385 → D-389로 개명했다(앞 번호들은 병합 시점마다 main의 다른 ADR이 먼저 차지했다).

**Context:**

1. D-180 이후 Imager는 `--disable-verify`로 돌고, 카드 전체를 이미지와 바이트 단위로 비교하는 readback이 유일한
   매체 검증이다(D-187, D-188).
2. 2026-10-01 release 009 카드(rosy-pinky-9dfk): PC CPU가 100%라 readback이 1–3 MB/s로 떨어져 ETA가 1.5시간이 됐다
   (디스크 큐 0). 로봇은 카드가 바로 필요했다. 운영자는 커밋 안 된 로컬 사본에서 readback 블록을 stub으로 바꿔
   `-ResumeAfterWrite`로 돌렸다. 증거는 `media_readback.skipped` 문자열 하나뿐이었고, 재공급(`-ReprovisionReceipt`)은
   그 receipt를 거부하므로 같은 신원으로 다시 쓸 길이 없었다.

**Decision:**

1. **표준 절차가 기본이다.** `write-card.ps1`은 그대로 전체 readback까지 한다. 긴급 절차는 명시 스위치
   `-Emergency`와 필수 `-EmergencyReason`(10–200자 인쇄 가능 ASCII, 큰따옴표·백슬래시 없음 — 관리자 창으로 넘기는
   인용이 깨지지 않게)으로만 켜진다. 이유가 없으면 UAC 전에 거부하고, `-PlanOnly`에는 쓸 수 없다.
2. **건너뛰는 것은 전체 readback 하나다.** 서명 검증, 시리얼 선택, plan 고정, 사전 측정, ERASE 확인, 카드 재확인은 그대로다.
   싼 점검 하나는 남긴다: 쓰기 뒤 카드 첫 섹터의 MBR disk signature가 이미지와 같아야 한다.
   **긴급 resume(`-Emergency -ResumeAfterWrite`)은 이 카드의 이전 시도 기록이 깨끗할 때만 된다.** 표준 resume은 전체 readback이
   카드를 다시 판정하지만 긴급 resume에는 그 판정이 없어서, 이미 readback 불일치로 "카드 교체"가 나온 카드나 stall
   watchdog이 죽인 쓰기에도 receipt가 나갈 수 있었다(독립 리뷰 HIGH). 그래서 긴급 resume은 reviewed plan(`-PlanPath`)을
   요구하고, 같은 plan의 진행 파일(plan 폴더·로그 폴더의 `*.progress.jsonl`, 현재 파일은 이번 시도 이전 줄)을 읽는다.
   마지막 전체 쓰기 시도가 Imager 정상 종료(exit 0 뒤 `readback` 단계 진입)까지 갔고, 그 뒤 어떤 시도에도 쓰기 단계 실패
   (stall·kill·exit≠0), readback 불일치(`kind: mismatch`), 이미지 오류(`kind: image`)가 없을 때만 허용한다. 즉 허용되는
   마지막 상태는 정상 종료 뒤의 `written-unverified`나 `unverified-no-bundle`이다. 기록이 없으면 거부한다.
   **이력의 출처는 plan 옆의 시도 색인 `<plan>.attempts.jsonl`이다**(검증 MEDIUM: `-EvidenceDir`·`-LogPath`로 로그를 다른
   곳에 두면 폴더 탐색으로는 그 시도의 불일치가 보이지 않았다). plan을 쓰는 모든 쓰기·resume은 `-LogPath`와 상관없이
   시작할 때 자기 진행 파일 경로를, 끝날 때 마지막 `card_state`와 실패 `kind`를 이 색인에 덧붙인다(append-only). 긴급
   resume은 이 색인에 적힌 진행 파일만 읽고, 이번 실행 전에 색인이 없거나 적힌 진행 파일이 없거나 읽을 수 없으면 거부한다.
   남는 위험: 운영자가 진행 파일이나 색인을 지우거나 옮기면 이력이 사라진다. 색인이 없으면 거부하지만, 색인 안의 한 줄을
   손으로 지운 것까지는 알 수 없다.
3. **증거는 정직하게.** 진행 파일 `bundle`/`unverified-no-bundle`, `receipt`/`complete-unverified`,
   `done`/`complete-unverified`(receipt 단계에서 창이 죽어도 검증된 카드처럼 보이지 않게), 상태 명령
   `Result: COMPLETE, NOT VERIFIED`, 창 경고 두 번(ERASE 전·끝). receipt는
   `media_readback={verified:false, skipped:"emergency", bytes_verified:0, sanity:{...}}`와
   `emergency={reason, at, readback:"skipped", registry, follow_up}`. 로봇 번호·이름·UID는 registry에 예약된 채로 남고
   receipt가 그렇게 적는다.
4. **후속 검증.** 첫 부팅 전이면 `verify-emergency-card.ps1`이 같은 카드를 읽기 전용으로 다시 읽는다. boot 파티션에서
   쓰기가 더한 `rosy-provision/`·`rosy-config.yaml`만 이름을 남기고 허용한다(`verify-media-readback.py --allow-boot-extra`).
   성공하면 원 receipt 옆에 `<receipt>.readback.json`(원 receipt sha256 포함)을 쓰고, 원 receipt는 바꾸지 않는다.
   이 허용은 시험 fixture에서도 카드 이미지의 FAT 파티션 안에 bundle과 설정 파일을 실제로 넣어 증명한다(다른 파일이
   다르면 실패).
   부팅한 카드는 이미지와 같을 수 없으므로 readback 대신 **장치 위 검증**을 한다: 활성 릴리스 파일을 서명된 릴리스의
   `SHA256SUMS`로 다시 해시하고(`sha256sum -c`), OS 패키지는 `dpkg --verify`로 설치 파일과 패키지 해시를 대조한다
   (2026-10-01 rosy-pinky-9dfk에서 이렇게 했다). 설정 파일처럼 첫 부팅이 바꾸는 항목의 차이는 목록으로 남기고 판단한다.
   이것은 부팅 뒤의 파일 무결성 증거이지 카드 바이트 전체의 MEDIA 증거가 아니므로, 기회가 되면 표준 쓰기로 다시 쓴다.
5. **재공급.** `-ReprovisionReceipt`는 긴급 receipt를 표준 쓰기에서만 받는다(새 receipt `supersedes.emergency: true`).
   긴급 receipt로 또 긴급 쓰기를 하면 거부한다. `emergency` 기록 없는 미검증 receipt는 예전처럼 거부한다.
6. **같은 날의 SSH 갭(모터 커미셔닝).** `enable-motor-commissioning.ps1`은 기본 `~/.ssh` 별칭만 써서 새 카드에서
   `No ED25519 host key is known`으로 실패했다(운영자가 로컬 사본을 고쳐 돌렸다). `rosy-release-push.ps1`과 같이
   `-KeyPath`(기본 `%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519`), `-KnownHosts`(기본 `%LOCALAPPDATA%\Rosy\known_hosts`),
   `-RosyUser`(기본 `rosy`)를 받아 `-i`·`IdentitiesOnly=yes`·`UserKnownHostsFile`·`-l`로 넘긴다. 호스트 키 확인
   (`StrictHostKeyChecking=yes`)과 `BatchMode`는 그대로이고, 키나 known_hosts 파일이 없으면 로봇에 닿기 전에 멈춘다.

**Consequences:**

- 긴급 카드의 부팅 결과는 BOOT·DEVICE 증거일 뿐 MEDIA 증거가 아니다. 조용히 잘못 써진 카드는 부팅 실패나 나중의 파일
  손상으로 드러난다.
- 느린 readback의 첫 조치는 CPU를 비우거나 verifier 우선순위를 올리는 것이다(런북). 긴급 절차는 그래도 기다릴 수
  없을 때만 쓴다.
- 운영자의 로컬 stub과 커미셔닝 사본(`.worktrees/card-emergency`)은 이 결정으로 대체된다.
- 순서 기록: 결정 1–5의 코드는 이 ADR보다 먼저 커밋됐다(같은 브랜치). 이 ADR이 그 결정을 모두 적고, 결정 6은 코드보다 먼저 적었다.
  독립 리뷰(REQUEST CHANGES)의 긴급 resume 이력 검사, receipt 단계 상태, 이유의 백슬래시 금지도 코드보다 먼저 여기에 적었다.
- 결정 6의 `-l rosy`는 맞다: `rosy`는 암호 없는 sudo를 가지며, 2026-10-01 rosy-pinky-9dfk에서 이 키 경로로
  `sudo -n python3 -`를 실행했다.

**Validation:**

- `test/test_sd_writer_contract.py`: 긴급 쓰기가 readback만 건너뜀(표준이면 실패하는 카드로), receipt 표시, 이유 누락·짧음·따옴표
  거부, pre-write 게이트(확인·서명·기존 receipt) 유지, MBR 점검, plan 금지, 재공급 수용·연쇄 거부, 후속 readback 성공·실패·
  비긴급 receipt 거부·fixture 경계.
- `test/test_sd_write_card_entrypoint.py`: 인자 전달, UAC 전 거부, 상태 명령 `NOT VERIFIED`.
- `test/test_media_readback.py`: `--allow-boot-extra`가 쓰기 파일만 허용하고 다른 추가 항목·바뀐 파일은 여전히 실패.
- 각 게이트를 끈 변이 13종이 모두 해당 테스트를 실패시킨다.
- 결정 6: `enable-motor-commissioning.ps1 -PrintSshArguments`로 해석된 ssh 인자를 호스트에서 확인한다(로봇 접속 없음).
