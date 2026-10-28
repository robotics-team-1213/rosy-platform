# Pinky OS ARM SYSTEM 양방향 검증

검증 source commit: `6fa2a37429a68486547bd892d96616a630879eb5`.
AI 시험 PC의 disposable QEMU AArch64 guest 두 개에서 source-slot a·b 각각 통과했다.
실제 Pi, 제품 release image 또는 현장 수용 기록은 아니다. DT·정책·native application은 fixture다.

## 실행과 결과

원격 runner에 다음 시험 인자를 전달했다. `--log-dir`에는 아래 외부 보존 위치를 사용했다.

```text
python tools/remote/remote_pytest.py --sha 6fa2a37429a68486547bd892d96616a630879eb5 --log-dir "<external>/arm-offline-6fa" -- ROSY_RUN_OS_SYSTEM_TESTS=1 ROSY_JOB_CORES=4 ROSY_JOB_MEM_GB=16 ROSY_JOB_RESERVE_GB=16 test/test_os_system_arm_vm.py::test_actual_arm_kernel_exposes_strict_synthetic_boot_properties -n 2 -vv -rA
```

- 실행 결과: 2 passed, 0 skipped, 3794.66초. Remote pytest와 launcher 모두 exit 0.
- 기존 실패 비교: 0 NEW, 0 known, 0 flaky. Quarantine 또는 timeout 변경으로 통과시키지 않았다.
- 메모리 peak: 14,109 MiB. 두 guest의 예약은 4 cores/16 GiB였다.
- 보존 위치: 워크스페이스의 `Rosy/artifacts/receipts/2026-10-27-full-os-integration/arm-offline-6fa/run-1.txt` (Git 밖).
- 로그 SHA256: `7ae39fb4b713a0a2d310998f5647024698ac877d2f3a02d16a79b0f1007a4b25`.
- 별도 cleanup 확인: 해당 run 디렉터리·lock 없음, owned QEMU process 0. Runner의 사용자 임시 경로 경고까지 모두 정리됐다는 뜻은 아니다.

## 통과한 조건

`test/test_os_system_arm_vm.py`의 두 parametrized 시험이 다음 조건을 검사하고 통과했다.

1. 실제 emulated AArch64 kernel·PID1 systemd·전용 virtio GPT media에서 비활성 슬롯 설치와 실제 device-policy grant/deny 검사.
2. 설치한 target root의 합성 DT/tryboot 시험 부팅과 정상 QEMU reboot 종료. 실제 Pi firmware의 자동 슬롯 선택은 검증하지 않았다.
3. 원래 cloud root를 observer로 부팅한 뒤, 물리 GPT와 owned instance를 확인하고 target root만 `ro,noload,nodev,nosuid,noexec`로 열어 journal readback.
4. 단일 새 trial boot의 probe sender·boot ID·실제 root·slot·DT partition/tryboot·timer 활성 상태와 180초 설정 결속.
5. 같은 boot의 deadline 서비스 PID1 `UNIT_STARTING` 이벤트에 monotonic 180초 이상 조건 적용. 완료 이벤트만으로 양수 시작 시각을 대체하지 않았다.

성공 stdout에는 raw journal/reboot marker가 남지 않았다. 원문 journal은 시험 중 검증됐지만 독립 보존되지 않았다.
따라서 개별 이벤트의 실제 timestamp를 이 외부 로그에서 직접 확인했다고 주장하지 않는다.
결과 로그, 실행 source의 assertion, 독립 source/evidence 검토를 함께 해석해야 한다.

## 관측자 수정의 이유

진단 source commit `04fa28a9438a0edd80b0c280db9fe55ff869366d`에서는 의도한 uncommitted-trial recovery가 SSH 준비보다 먼저 guest를 종료했고,
기존 `restart_slot()`의 `wait_boot()`가 이를 오류로 처리했다. 보존된 console에는 정상 shutdown과 kernel uptime 237.759508초의 reboot 요청이 있었다.
그 진단 실행은 첫 케이스 실패·두 번째 케이스 중단으로 끝났으며 통과 증거로 사용하지 않는다.

제품의 180초 제한을 유지하고, 시험 전용 persistent journal/probe와 SSH를 기다리지 않는 trial 시작을 사용했다.
다음 observer는 source 슬롯 대신 원래 cloud root를 사용하므로, 증거 수집 전에 source lifecycle recovery가 공통 pending 상태를 바꾸지 않는다.
잘못된 DT 값과 쓰기 가능한 mount를 넣은 변이는 5개 회귀를 실패시켰고, 보호 복원 후 일반 회귀 102개가 통과했다(실제 SYSTEM opt-in 6개 별도 제외).

## 통합 범위와 남은 수용

후속 source commit `2f8d7fd9af15a432a44269a8ba3b4bf05837b2f9`의 관련 회귀는 141 passed/6 opt-in skipped/0 NEW였다.
여기에는 Python의 seal 상수 이름을 제거한 상태에서 실제 CMS/verity bundle을 검증하는 경우가 포함된다.
잘못된 seal 연산값을 주입하면 실제 검증기가 HOLD/EINVAL로 거절하는 것도 별도 확인했다.
이 후속 검증은 위 ARM run의 source SHA를 바꾸거나 최신 source 전체의 ARM 실행으로 승격하지 않는다.

새 native ARM64 release-image build, 실제 Windows OS bundle 준비·서명·engineering 게시, healthy trial commit 왕복,
실제 Pi firmware·hardware watchdog·전원 차단·실물 Wi-Fi/보정 보존과 FIELD 수용은 이 기록의 범위 밖이다.
Production BUILD_GO/HOLD와 rollout 승격 조건은 유지한다.

CE: 해당 없음 — 복구가 SSH readiness를 앞설 수 있다는 이유와 observer 선택 원칙을 코드 주석·회귀·이 검증 기록에 남겼다. 별도 교훈 문서는 중복 작성하지 않았다.
