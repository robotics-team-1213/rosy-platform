# D-859 — 현장 NTP 계층과 공통 UTC 시간 동기화

**Status:** Accepted (2026-10-24; 사용자 요청으로 결정·구현)

클라이언트의 복수 source 허용은 [D-861](D-861-one-identical-ntp-endpoint-for-all-devices.md)로 대체됐다. 모든 기기는 같은 현장 NTP endpoint 하나를 사용한다.

## 배경과 대안

CORE SRS §25는 UTC 기록과 chrony를 권고한다. Pinky 이미지는 chrony를 설치·활성화하지만 기본 Ubuntu 시간원과 PC들의 시간원을 통일하지 않는다. `publish_payload_release.py`의 시각 비교, World의 future/stale 판정, 카메라·로그 상관은 장치 간 시계가 가깝다는 전제에 의존한다.

각 장치의 공용 NTP 직결은 단순하지만 현장 인터넷 차단과 서로 다른 시간원 정책을 통제하기 어렵다. PTP/GNSS는 하드웨어 타임스탬프·유선망·별도 기준 장비의 수용 증거가 없다. 기존 chrony를 활용한 **관제 PC 중심 NTP 계층**을 선택한다. 애플리케이션에서 OS 시각을 임의 보정하는 별도 프로토콜은 만들지 않는다.

## 결정

1. 관제 PC는 운영자가 지정한 서로 다른 외부 NTP 서버 이름 최소 3개를 사용한다. 운영자는 실제로 독립된 시간원인지 확인한다. `allow`에 명시한 현장 CIDR에만 UDP 123으로 응답한다. 공개 저장소에는 실제 주소·이름·CIDR을 넣지 않는다. NTP는 현장 신뢰망에 한하며 인터넷 공개 및 WAN 포트 전달을 금지한다. 원격 명령은 loopback으로 제한한다.
2. 모델·AI·OMX/카메라 호스트·Pinky 등 Linux 장치는 승인된 관제 NTP 서버만 따른다. 컨테이너는 호스트 커널 시계를 공유하며 CAP_SYS_TIME을 받지 않는다. 시간 동기화 책임은 호스트 운영자에게 있다. CORE/Fleet에는 root 시각 변경 권한을 추가하지 않는다.
3. `/etc/chrony/chrony.conf` 전체를 관리해 배포 기본 pool, DHCP `sourcedir`, 다른 include에 의한 시간원 혼입을 방지한다. 적용 전 원본을 보존하고 `chronyd -p`로 구문 검사한다. 서비스 활성화/재시작 실패 시 원본을 복구한다. 미설치 chrony는 유지보수 절차에서 먼저 설치한다. 자동 복구 타이머가 시계 설정을 고치거나 데몬을 재시작하지 않는다.
4. `makestep 0.1 3`은 데몬 시작 후 처음 세 번 갱신에 한해 큰 오차를 보정한다. **chrony 재시작도 그 창을 다시 연다.** 설치에는 `--maintenance`와 알려진 런타임 중지 확인이 필요하다. 운영자는 별도 컨테이너·OMX·수집 작업도 중지한다. 운전 중 `chronyc makestep`, 수동 날짜 변경, 무제한 step은 금지한다. 정상 운전은 slew를 사용한다. 기록은 UTC ISO 8601, timeout·watchdog·lease의 경과 시간은 monotonic을 유지한다. 표시 시간대는 별개다.
5. 읽기 전용 `check`는 chrony 활성, `Normal` leap 상태, stratum 1–15, 마지막 기준 표본 나이 0–180초, `abs(remaining correction) + root delay/2 + root dispersion <= 0.05초`를 모두 요구한다. NaN·무한대·음수 거리·잘못된 출력은 거부한다. 이는 chrony가 보고한 UTC 오차 상한의 운영 기준이며 센서 노출·전송 지연·정밀 하드웨어 동시성 보증은 아니다. 두 호스트가 모두 통과하면 보고된 오차 상한의 합은 최대 100ms다. 기존 freshness/안전 검사를 완화하지 않는다.
6. 상위망 단절 시 chrony는 기존 추정으로 holdover하되 `local stratum`으로 자체 시각을 UTC 정본처럼 광고하지 않는다. 오래되거나 오차가 커진 표본은 check에서 실패한다. 재부팅 후 동기 전에도 실패한다. 실패는 운영 수용 불가이며 시간 의존 작업을 운영자가 보류한다. 이 변경은 애플리케이션 자동 admission gate를 추가하지 않는다. 신규 복구 시 동기를 확인하고 작업을 재개한다. 관제 PC 중단은 현재 단일 장애점이다. 필요하면 같은 UTC 정책의 두 번째 현장 서버를 별도 수용한다.
7. Windows 개발 PC는 W32Time의 NTP client mode(`,0x8`)로 같은 관제 서버를 사용한다. 도메인/정책 관리 호스트는 설치 스크립트가 거부하고 관리자가 계층을 설정한다. registry 백업을 남긴다. `/resync` 성공만으로 50ms 수용을 주장하지 않는다. Windows는 별도 source·마지막 성공 시각·offset 관측이 필요하다.
8. 모바일 카메라/MCU의 OS 시계는 일반 앱이 강제 설정하지 않는다. 관리 가능한 장치는 OS/MDM NTP를 같은 기준으로 설정한다. 불가능한 장치는 미동기로 표시하고 수신 호스트 UTC와 원본 capture timestamp/clock domain을 구별한다. 모바일·MCU까지 완료됐다는 수용은 장치별 증거 전에는 금지한다. 시뮬레이션 `/clock`과 물리 장치 UTC를 섞지 않는다.

## 구현과 수용

공통 도구는 `deploy/hosts/common/rosy_time_sync.py`, Windows는 `install-time-sync.ps1`이다. Linux 도구는 Pinky의 독립 native runtime 사본에도 포함한다. 이미지에는 현장별 이름을 굽지 않고 설치·장치 등록 때 명시한다. 기존 이미지/PC는 도구를 직접 적용한다. [설치·점검·복구](../../deploy/hosts/README.md#공통-시간-동기화-d-859)를 따른다.

코드 수용: `test/test_time_sync.py`가 계층 설정, 입력 주입/전체망 거부, 미동기·stale·오차 및 유지보수 경계를 확인한다. Linux 실물 수용은 관제→각 클라이언트 순서로 설정하고 각 `check` 및 `chronyc sources -v`를 기록한다. 연결 단절·재연결·재부팅 후 재확인한다. 방화벽은 기존 소유 절차로 승인된 인터페이스/CIDR에 UDP 123만 허용한다. 적용 성공과 실제 전체 장치 수용은 별도다.

## 근거

- [chrony 4.5 설정: server, allow, makestep, local](https://chrony-project.org/doc/4.5/chrony.conf.html)
- [chronyc: tracking, waitsync, 시계 점프 주의](https://chrony-project.org/doc/4.5/chronyc.html)
- [Microsoft W32Time 구성·점검](https://learn.microsoft.com/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings?tabs=config)
