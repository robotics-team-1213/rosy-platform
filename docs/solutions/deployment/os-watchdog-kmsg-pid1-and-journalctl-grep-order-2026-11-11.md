---
title: "Real Pi OS watchdog admission failed on early-boot kmsg PID1 fields and journalctl -n --grep ordering"
date: "2026-11-11"
category: deployment
module: deploy/robot/pinky_pro/native
problem_type: integration_issue
component: deployment
symptoms:
  - "os_update_controller.py install fails with OS_WATCHDOG_HOLD on real Raspberry Pi 5 devices"
  - "journalctl --grep=watchdog|Watchdog _PID=1 returns 0 lines on normal boot"
  - "journalctl --grep=watchdog|Watchdog -n 64 returns matching lines in newest-first monotonic timestamp order"
root_cause: logic_error
resolution_type: code_fix
applies_when:
  - "observing PID 1 hardware watchdog open and enable messages in systemd-journald on Ubuntu 24.04 (systemd 255)"
  - "combining journalctl --grep with -n (--lines) when chronological monotonic timestamp ordering is required"
---

# 실물 Pi에서 OS 업데이트 워치독 관측이 kmsg 필드와 journalctl 역순 출력으로 막힌 경우

## 증상과 확인 근거

실물 Pinky Pro 기체(Raspberry Pi 5, Ubuntu 24.04, `systemd 255.4`)에서 A/B OS 번들 설치를 시도할 때
[os_update_watchdog.py](../../../deploy/robot/pinky_pro/native/os_update_watchdog.py)가 항상 `OS_WATCHDOG_HOLD`로 거절했다.

실물 기체에서 확인한 사실은 두 가지다.

1. `systemctl show`의 `RuntimeWatchdogUSec=10s`, `RebootWatchdogUSec=10s`, `WatchdogDevice=/dev/watchdog0`,
   `/sys/class/watchdog/watchdog0/state=active`, `timeout=10`, `open_timeout=180`은 모두 정상이었다.
2. 그러나 부팅 초반 PID 1이 `/dev/watchdog0`을 열고 활성화할 때는 `systemd-journald` 시작 전이라 `/dev/kmsg`로 기록된다.
   이후 `systemd-journald`가 이를 수입하면 `_TRANSPORT="kernel"`, `SYSLOG_PID="1"`, `SYSLOG_IDENTIFIER="systemd"`만 붙고
   `_PID="1"`, `_UID="0"`, `_COMM="systemd"` 필드는 존재하지 않는다. 따라서 `_PID=1` 단독 필터는 정상 부팅에서 항상 0행을 반환했다.
3. 런타임 중 PID 1이 워치독을 재설정해 `_PID="1"` 행이 2개 이상 생기더라도, `systemd 255.4`의 `journalctl`은
   `-n 64`와 `--grep=...`을 함께 주면 저널 끝에서 역방향으로 탐색하며 최신 행부터 출력한다.
   이로 인해 `__MONOTONIC_TIMESTAMP` 단조 증가 검사가 2행 이상에서 항상 실패했다.

## 원인과 수정

1. **초기 부팅 PID 1 kmsg 행 인정**:
   [os_update_watchdog.py](../../../deploy/robot/pinky_pro/native/os_update_watchdog.py)의 `_is_pid1`에서
   기존 소켓 기반 `_PID="1" and _UID="0" and _COMM="systemd"` 행뿐 아니라,
   `_TRANSPORT="kernel" and SYSLOG_PID="1" and SYSLOG_IDENTIFIER="systemd"`이면서 `_PID`·`_UID`가 없는
   초기 부팅 PID 1 kmsg 수입 행을 함께 인정한다.
2. **`journalctl` 정방향 조회 및 필터 결합**:
   `journalctl` 호출에서 `--grep`과 결합될 때 역순 출력을 유발하는 `-n 64`를 제거하고(출력 크기는 기존 `262144` 바이트 한도로 제한),
   `_PID=1 + _TRANSPORT=kernel SYSLOG_PID=1 SYSLOG_IDENTIFIER=systemd` 디스정션 필터로 초기 부팅과 런타임 재무장 행을 모두 시간순으로 읽는다.

## 검증과 배포 경계

- [test_os_update_watchdog.py](../../../test/test_os_update_watchdog.py)의 `test_early_boot_kmsg_pid1_watchdog_journal_and_chronological_grep_flags`에서
  초기 부팅 kmsg PID 1 워치독 로그 허용, 비-PID 1(`SYSLOG_PID="2"`) 거절, `-n` 미사용 및 `+ _TRANSPORT=kernel` 인자 구성을 검증한다.
- `os_update_watchdog.py`는 frozen OS bootstrap 소유이므로 이미 배포된 구 OS 이미지 기체의 `/opt/rosy/os-bootstrap`은
  새 서명 OS 이미지(또는 SD 재기록)로 갱신될 때 반영된다.
