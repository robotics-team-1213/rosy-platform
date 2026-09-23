## D-175 디버그 로그는 CORE가 죽어도, 네트워크가 없어도, 장비가 없어도 읽을 수 있어야 한다

**Status:** Accepted (2026-09-22). D-174(첫 부팅 결함·부팅 표시)과 짝을 이룬다. D-174 T0은
사람에게 "지금 상태"를 보여 주고, 이 ADR은 운영자와 개발자에게 "왜 그렇게 됐는지"를 남긴다.

**Context:** 첫 실기 부팅(D-173 카드)에서 CORE가 뜨지 않았을 때 원인을 알아내는 데 다음 과정이 필요했다.

1. 카드 회수
2. 관리자 권한으로 물리 디스크를 읽기 전용으로 열기
3. 순수 Python ext4 파서로 파일 추출
4. WSL `journalctl -D`로 journal 읽기

원인 한 줄(`No module named 'signing'`)은 부팅 8초에 이미 journal에 있었다. 기존 관측 수단은 다음과
같은데, 모두 이번 실패 상황에서 쓸 수 없었다.

| 수단 | 위치 | 이번 실패에서 |
|---|---|---|
| `/api/v1/logs/audit`, `/api/v1/events`, 진단 수집기(DIAG/OBS) | CORE 프로세스 안 | CORE가 안 떠서 없음 |
| Host Agent 감사 로그 | 장치 파일 | 원격 접속 경로가 없어 못 읽음 |
| `deploy/robot/verify/device_readback.py` | 운영자가 장치에서 실행 | 컨테이너 시대 가정, 원격 접속 없음 |
| journald | ext4 루트 `/var/log/journal` | Windows에서 읽을 수 없음. `wsl --mount`는 USB 리더 미지원 |

관측이 전부 "CORE가 살아 있고 네트워크로 닿는다"는 전제 위에 있었다. 부팅 실패는 정확히 그 전제가
깨지는 상황이다.

**Decision:** 디버그 로그를 네 층으로 둔다. 아래 층일수록 더 적은 것을 전제한다.

| 층 | 전제 | 무엇 | 어디 |
|---|---|---|---|
| **L0 원장** | 없음 | journald persistent, 용량 상한 drop-in(`SystemMaxUse`), 모든 ROSY unit은 journal로만 기록 | ext4 `/var/log/journal` |
| **L1 블랙박스** | 카드만 있음 | 부팅 단계 전이와 실패 때마다 비밀 없는 요약을 쓴다. 단계, 실패 unit, 그 unit의 마지막 로그 N줄, release·revision, 장치 이름·UID·번호, IP·SSID(PSK 없음), boot_id, 시각. 최근 5회 부팅분만 회전 보관하고 크기 상한을 둔다 | **FAT32 boot 파티션** `rosy-diag/` — Windows에 꽂기만 하면 읽힌다 |
| **L2 수집 번들** | 네트워크 + 운영자 키 | 장치 CLI `rosy-diag collect`가 비밀 없는 tar를 만든다: ROSY unit journal export, `systemctl status`, provisioning 상태, release 활성화 기록, dmesg, 네트워크 상태 요약. Windows `collect-rosy-diagnostics.ps1`이 SSH로 가져온다. SSH가 안 되면 카드 경로(L1 + D-174 F8 읽기 전용 ext4 도구)로 자동 전환 | 운영 PC `evidence/<device>/<boot_id>/` |
| **L3 실행 중 API** | CORE 기동 | 기존 audit·events·diagnostics에 더해 L1 요약을 읽기 전용 admin API로 노출 | CORE `/api/v1` |

공통 규칙은 다음과 같다.

- **비밀 없음이 기본값이다.** 모든 층은 같은 redaction 모듈을 거친다(`deploy/release/secret_scan.py`
  규칙 재사용). NetworkManager 연결 파일, 개인화 bundle, API 토큰, 개인키는 수집 대상이 아니다.
  L1은 카드를 가진 누구나 읽을 수 있으므로 특히 엄격하다.
- **상관관계 키를 통일한다.** 모든 기록에 `boot_id`, `release_id`, `device_name`, 단조 시간을 붙여
  층 사이를 잇는다.
- **CORE 밖, 최소 권한으로 둔다.** L1 작성자는 D-174 T0 `rosy-boot-status`와 같은 단계 계산 모듈을 쓰는
  root oneshot이다. 대상 unit의 `OnFailure=`와 runtime 성공 시점에 돈다. CORE 기동을 막지 않는다(`Wants`).
- **L4 중앙 집계는 열지 않는다.** 중앙 Fleet 착수(D-170)와 함께 별도 ADR로 연다.

**Alternatives:**

- CORE 로그 API 확장만: 이번 실패에서 CORE는 존재하지 않았다.
- journal 전체를 boot 파티션에 복사: 크기가 크고, 비밀 필터를 거치지 않은 원문이 누구나 읽는 FAT32에
  남는다.
- 원격 로그 서버(syslog/Loki)로 즉시 전송: 네트워크가 가장 먼저 깨지는 층이고, 중앙 서버는 아직 없다.
- 카드 회수 + ext4 추출만 운영 절차로 삼기: 이번에 동작은 했지만 관리자 권한과 수 분의 수작업이
  필요하고, 현장 인력에게 넘길 수 없다.

**Consequences:** 부팅 실패는 카드를 PC에 꽂는 즉시(L1), 또는 SSH 한 줄로(L2) 원인까지 보인다.
boot 파티션에 쓰기가 생기므로 쓰기 횟수와 크기 상한을 계약으로 고정해야 한다. redaction 누락은 곧
유출이므로 시험을 먼저 쓴다. L3 API는 CORE 계약(API Ref) 개정이 필요하므로 L0-L2 뒤로 둔다.

**구현·처리 계획:**
[`docs/plans/2026-09-22-rosy-debug-log-system.md`](../plans/2026-09-22-rosy-debug-log-system.md).
D-174 계획의 Task 5(부팅 표시 T0)·Task 8(카드 진단 도구)과 단계 계산·카드 읽기를 공유한다.

**Validation / Transition:** 수용 기준은 이번 결함(F1)을 의도적으로 재현한 이미지로 다음 세 가지를 보이는 것이다.

1. 카드를 PC에 꽂으면 `rosy-diag/latest.txt`에 `FAILED: rosy-release-recover`와 `No module named 'signing'`
   줄이 보인다(L1).
2. SSH가 되는 장치에서 `collect-rosy-diagnostics.ps1`이 같은 원인을 담은 번들을 만든다(L2).
3. 두 산출물 모두 secret scan을 통과한다.
