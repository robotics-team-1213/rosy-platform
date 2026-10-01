## D-406 로봇은 GitHub Releases에서 서명된 payload를 스스로 받아, 쉬고 있을 때 승인 없이 적용한다 — 로봇별 hold가 시험과 봉인을 지킨다

**Status:** Accepted (2026-10-01).
- 사용자가 운용 방식으로 "완전 자동(유휴 시)", 받는 곳으로 "GitHub Releases", 배포 기준으로 "이 PC의 배포 명령", 보호 방식으로 "로봇별 고정(hold)"을 골랐다(2026-10-01). 구현 방식은 "로봇이 스스로 가져감 + 카나리 1대 확인 뒤 나머지"(A안)를 승인했다.
- **D-387을 개정한다.** 바뀌는 결정: 결정 2(카탈로그는 사이트 Fleet), 결정 5(운영자 승인), Alternatives의 "완전 자동 기각"과 "GitHub에서 직접 받기 기각". 유지하는 결정: 결정 1(한 서명 릴리스), 결정 3의 서명 검사 시점과 "스테이징과 적용 분리", 결정 4의 잠정 claim 규칙, 결정 10의 배터리 문턱(40%/충전 중)과 canary 대기 10분, 결정 6~7·P2·P4(3·4계층)는 범위 밖으로 그대로 둔다.
- D-197/D-198이 퇴역시킨 GitHub polling을 서명 검증·ETag·한도 아래에서 다시 쓴다.

### Context

- 2026-10-01 두 로봇(rosy-pinky-9dfk, rosy-pinky-8kcn)을 최신 main으로 맞추는 데 릴리스 세 개(019·020·021)와 두 시간이 걸렸다. 매번 PC에서 다운로드·서명·로봇별 push·확인을 손으로 했다(`docs/solutions/workflow-issues/release-cycle-time-one-release-per-deployment-2026-10-01.md`).
- 같은 날 활성화가 CORE를 재시작하지 않는 결함이 드러났고 고쳐졌다(`docs/solutions/runtime-errors/payload-activation-left-core-on-the-old-release-2026-10-01.md`). 고친 활성화기와 push의 `core-release-check`가 이제 "CORE가 실제로 새 릴리스에서 도는지"를 판정할 수 있다.
- 두 로봇 모두 `api.github.com`과 `github.com`에 닿는다(2026-10-01 읽기 전용 확인, NTP 동기). 저장소는 공개라 payload 공개는 새 노출이 아니다.
- 로봇은 여러 세션이 공유한다. 같은 날 9dfk는 G4 녹화 사이에 IDLE이었고, 봉인은 릴리스에 묶여 있다. 유휴 판정만으로는 시험·봉인을 지킬 수 없다.
- D-387의 Fleet 카탈로그·정비 리스·업데이트 전용 자격은 아직 구현되지 않았다(코드 없음).

### Decision

**1. 배포 = 이 PC의 발행 명령 하나.**
- `tools/release/publish_payload_release.py`가 `prepare_payload_release.py`의 서명된 tarball을 받아 GitHub Release `payload-<release-id>`를 만든다. 자산은 셋이다: `<id>.tar.gz`, `rollout.json`, `rollout.json.sig`.
- 서명 키는 이 PC에만 둔다. CI에 키를 두지 않는다(D-145 유지). main push만으로는 로봇이 바뀌지 않는다.
- `rollout.json` 필드: `schema`, `release_id`, `tarball_sha256`, `source_revision`, `published_at`(UTC), `canary`(호스트 이름 목록), `canary_ok`(bool), `wave_delay_s`(기본 600), `withdrawn`(bool), `reason`.
- `rollout.json`은 릴리스 키로 서명한다(`rollout.json.sig`). 로봇은 서명이 맞지 않는 rollout을 무시한다. 그래서 GitHub 쓰기 권한만 가진 사람은 시점·대상·철회를 바꿀 수 없다.

**2. 카나리와 철회는 발행 명령이 맡는다.**
- 발행 직후 `canary_ok=false`다. `canary`에 이름이 있는 로봇만 적용할 수 있다.
- 발행 명령은 카나리 로봇의 업데이트 상태(`/var/lib/rosy/updates/status.json`, ssh 읽기 전용)를 지켜본다. 카나리가 이 릴리스로 커밋하고 건강 판정을 통과하면 `canary_ok=true`로 다시 서명해 올린다.
- 카나리가 되돌리거나 30분 안에 적용하지 못하면 `withdrawn=true, reason=…`으로 올린다. 나머지 로봇은 받지 않는다.
- 나머지 로봇은 `canary_ok=true`이고 `published_at + wave_delay_s`가 지났을 때만 적용한다.
- PC가 중간에 꺼지면 카나리 외 로봇은 기다린다(멈춤이 기본값). 발행 명령을 다시 실행하면 이어서 한다.
- 되돌리기는 새 릴리스를 발행하거나 운영자가 `rosy-release-push.ps1 -Rollback`을 쓴다. 로봇은 지금보다 낮은 id를 자동으로 적용하지 않는다.

**3. 로봇 쪽 업데이터 (`rosy-auto-update.timer` → `.service`, root, oneshot).**
- 코드는 `/opt/rosy/native-runtime/rosy_auto_update.py`이고 D-388 image-layer sync로 설치·갱신한다. 10분마다, `RandomizedDelaySec`으로 흩어서 돈다.
- 상태는 `/var/lib/rosy/updates/`에 둔다: `config.json`, `hold.json`, `state.json`(ETag, 단계, 실패한 id), `status.json`(최근 결과), `history.jsonl`(추가 전용).
- 한 번 실행의 순서:
  1. **확인.** GitHub Releases API를 ETag 조건부 요청으로 읽고, 태그 `payload-*` 가운데 지금 릴리스보다 큰 id를 고른다. 304는 한도에 세지 않는다.
  2. **rollout 검증.** `rollout.json.sig`를 `/etc/rosy/trusted-release-keys`로 검증한다. 실패·철회·실패 기록이 있는 id는 건너뛴다.
  3. **스테이징.** tarball을 `.part`로 받아 `tarball_sha256`과 맞춰 본 뒤 `/opt/rosy/releases/<id>`에 풀고, 이미 설치된 검증기(`native_release.py verify`)로 서명을 검사한다. 쓰는 중이어도 스테이징은 한다(`Nice=19`, `IOSchedulingClass=idle`). `current`를 옮기지 않는다.
  4. **적용 시점.** 카나리이거나, `canary_ok`이고 대기 시간이 지났을 때.
  5. **적격성.** 아래가 모두 참일 때만 적용한다. 하나라도 거짓이면 이유를 `status.json`에 남기고 다음 실행을 기다린다.
     - hold가 없거나 만료됐다.
     - 지금 릴리스에 묶인 하드웨어 승인이 없다. `/etc/rosy/approvals/hardware.approved` 또는 `navigation.approved`의 `release_id`가 지금 릴리스와 같으면 hold로 본다(`mapping_approval.py check`가 릴리스를 바꾸면 그 승인을 무효로 하기 때문이다).
     - CORE가 IDLE이고 이동이 없다(10 s 동안 두 표본). navigation·line_follow·docking·swarm·교정 세션이 없고 E-stop이 걸려 있지 않다.
     - 배터리 40% 이상이거나 충전 중이다. 배터리 값이 없으면 부적격이다.
     - 다른 작업의 claim(`/run/rosy-claim`)이 없다. 업데이터는 적용 동안 스스로 claim을 잡는다.
     - **판정 입력은 토큰이 필요 없는 로컬 파일이다.** CORE가 10 s마다 쓰는 `/run/rosy/status-inputs.json`을 schema 2로 넓혀 `mode`, `navigation`, `velocity`, `battery.percent`, `battery_status.charging`, `docking.state`, `line_follow`, `swarm.active`, `safety.estop`, `activity`를 싣는다. 업데이터는 `rosy-boot-status.py`와 같은 규칙(O_NOFOLLOW, 크기 상한, 60 s 신선도)으로 읽고, 파일이 없거나 오래됐거나 schema가 다르면 부적격이다. `GET /api/v1/robot/state`는 토큰이 필요하고 업데이트 전용 자격(D-387 P3)이 아직 없으므로 쓰지 않는다.
  6. **적용 트랜잭션.**
     - `native_release.py activate` → CORE 프로세스 cwd 확인(아니면 rosy-core 재시작) → 새 릴리스의 `sync-image-layer.py` → 바뀐 유닛 재시작 → 건강 판정.
     - 건강 판정: CORE 준비(45 s), `rosy-core`·`rosy-io`·`rosy-camera`가 새 릴리스 cwd에서 active, 실패한 `rosy-*` 유닛 없음이 60 s 동안 유지.
     - 실패하면 `native_release.py rollback`과 되돌아간 릴리스의 sync로 되돌리고, 그 id를 실패로 기록해 다시 시도하지 않는다.
  7. **기록.** `history.jsonl`과 `status.json`에 단계·결과·이유·`boot_id`를 남긴다.
- 업데이터 자신이 바뀌는 릴리스는 다음 실행부터 새 코드를 쓴다(sync가 설치).

**4. 로봇별 hold.**
- `hold.json` = `{holder, reason, expires_at}`. 만료가 없는 hold는 받지 않는다(최대 7일).
- hold 동안에도 스테이징은 하고, 적용만 하지 않는다.
- 거는 방법: 이 PC의 `deploy/robot/pinky_pro/rosy-update-hold.ps1 -Robot <ip> -Hold -Reason … -Hours …`, 해제는 `-Release`, 상태는 `-Status`. 에이전트 세션도 같은 명령을 쓴다.
- 시험·주행·봉인을 시작하는 세션은 먼저 hold를 건다. 봉인된 승인이 있으면 hold가 없어도 자동으로 hold로 본다.
- `config.json`의 `enabled=false`는 로봇의 자동 업데이트를 끈다(벤치 작업용).

**5. 수동 경로는 그대로 두고, claim으로 업데이터와 겹치지 않게 한다.**
- `rosy-release-push.ps1`과 `-Rollback`은 그대로 쓴다.
- D-387 결정 4의 잠정 claim을 지금 구현한다. `sudo mkdir /run/rosy-claim`(원자적) 뒤 `claim.json`(holder, purpose, `expires_at`, `boot_id`)을 쓴다. push와 업데이터 모두 시작할 때 잡고 끝나면 놓는다. 만료된 claim은 `mv`로 한 쪽만 치운다.
- `rosy-release-unpack.sh`를 `deploy/robot/pinky_pro/native/`로 옮겨 로봇의 `/opt/rosy/native-runtime/`에도 깔리게 한다. push와 업데이터가 같은 압축 해제 규칙을 쓴다.

**6. 구현 경계.**
- 새 유닛 `rosy-auto-update.service`·`.timer`는 D-388 허용 목록(`UNITS`, `ENABLED_UNITS`), `build-native-payload.sh`의 복사 목록, `customize-rootfs.sh`의 enable 목록에 함께 넣는다(패리티 시험이 묶는다).
- 레거시 Docker 시대 `rosy-update-check.{service,timer}`와 `release/updater.py`는 되살리지 않는다.
- 첫 설치는 이 ADR을 담은 릴리스를 손으로 push할 때 sync가 한다. 그 뒤부터 업데이터가 스스로를 갱신한다.

### Alternatives

- **승인 후 자동(D-387 그대로).** 사용자가 이번에 완전 자동을 골랐다. 시험·봉인 보호는 hold가 맡는다.
- **사이트 Fleet 카탈로그.** 지금 Fleet에 카탈로그가 없다. 로봇이 GitHub에 닿으므로 먼저 GitHub으로 하고, 인터넷 없는 현장은 Fleet 카탈로그(D-387 P3)로 미룬다.
- **PC가 로봇이 쉴 때를 기다렸다가 밀어 넣기.** PC가 켜져 있어야 하고 로봇 스스로 업데이트하지 않는다. 기각.
- **main push마다 CI가 서명·발행.** 키를 CI에 두어야 하고(D-145), 승인 전 변경(같은 날 D-397)이 바로 로봇에 간다. 기각.
- **A/B 전체 이미지(RAUC 등).** D-387 P4로 남긴다.

### Consequences

- 배포가 명령 하나가 된다. 로봇이 꺼져 있었거나 망을 떠났다가 돌아와도 스스로 따라온다(카나리 확인 뒤).
- 로봇이 쉬는 사이 CORE·io가 재시작된다. hold를 걸지 않은 로봇은 예고 없이 바뀔 수 있다. 시험 세션은 hold를 먼저 건다.
- GitHub 장애나 인터넷 단절이면 업데이트가 멈출 뿐 로봇 운용에는 영향이 없다.
- 카나리 외 로봇은 PC의 카나리 확인이 있어야 움직인다.

### Risks

- **R1. hold를 잊은 시험.** 쉬는 사이 바뀌어 시험이 무효가 될 수 있다. 완화: 봉인 자동 hold, 스킬·runbook에 hold 단계 추가, `status.json`과 대시보드 표시(후속).
- **R2. GitHub 계정 탈취.** 내용은 위조할 수 없고(서명), rollout도 서명이라 시점·철회도 못 바꾼다. 서명된 옛 릴리스로 되돌리는 것은 "낮은 id 적용 안 함"으로 막는다.
- **R3. 적용 중 전원 차단.** `recover()`가 부팅 때 마지막으로 좋았던 릴리스로 돌린다. image layer 중간 상태는 다음 실행의 sync가 맞춘다.
- **R4. 이동 판정 오판.** IDLE·속도·모드·claim을 함께 보고, 적용 중 E-stop·정지 경로는 늘 열려 있다. 적용 동안 io가 재시작되며 모터는 잠깐 멈춘다.

### Validation

- HOST: 업데이터의 각 단계(ETag, rollout 서명 거부, 철회·실패 id 건너뜀, 낮은 id 거부, 적격성 각 조건, hold 만료, 봉인 자동 hold, 실패 시 되돌림과 재시도 안 함), 발행 명령의 카나리 판정과 철회, hold 명령. 각 가드는 변형으로 빨강을 확인한다.
- DEVICE: 두 대에서 발행 → 카나리 1대 자동 적용 → `canary_ok` → 나머지 자동 적용. hold 걸린 로봇이 건너뛰는지, 움직이는 로봇이 건너뛰는지, 일부러 실패하는 릴리스가 카나리에서 되돌려지고 철회되는지 본다.
- FIELD: 해당 없음.

### References

- D-387(개정 대상), D-388, D-225, D-145, D-197/D-198, D-389
- `docs/solutions/runtime-errors/payload-activation-left-core-on-the-old-release-2026-10-01.md`
- `docs/solutions/workflow-issues/release-cycle-time-one-release-per-deployment-2026-10-01.md`
