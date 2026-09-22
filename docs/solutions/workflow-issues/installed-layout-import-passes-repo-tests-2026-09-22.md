---
title: 저장소에서 통과한 런타임 도구도 설치 위치에서 실행해 봐야 하고, 카드만으로 진단할 길을 미리 만들어 둬야 한다
date: 2026-09-22
category: workflow-issues
module: deploy/robot/native + deploy/image (Pinky Pro 첫 실기 부팅)
problem_type: workflow_issue
component: development_workflow
severity: critical
applies_when:
  - 저장소 안의 스크립트를 이미지나 장치의 다른 경로(/opt/...)로 복사해 실행할 때
  - 스크립트가 __file__ 기준 상대 경로로 형제 모듈이나 설정을 찾을 때
  - 이미지 검증이 파일 존재·해시만 보고 진입점을 실행하지 않을 때
  - 장비가 없거나 원격 접속이 안 되는 상태에서 부팅 실패를 진단해야 할 때
symptoms:
  - 부팅 후 CORE API 8080이 닫혀 있고 부팅 소리·화면 등 사람이 볼 신호가 없음
  - SSH가 publickey만 받아 원격 진단 불가
  - "`rosy-pinky-e4us.local`은 안 풀리고 `ubuntu.local`만 풀림"
root_cause: missing_validation
tags: [installed-layout, native-runtime, image-verification, first-boot, offline-diagnosis, ext4, journald, pinky-pro]
---

# 저장소에서 통과한 런타임 도구도 설치 위치에서 실행해 봐야 하고, 카드만으로 진단할 길을 미리 만들어 둬야 한다

## Context

release `2026.09.22-002`를 서명·전체 readback까지 검증해 구운 카드로 Pinky Pro를 처음 부팅했다
(D-173). 첫 부팅 개인화는 `PROVISIONED`까지 갔고 Wi-Fi도 붙었지만 CORE는 한 번도 뜨지 않았다.
저장소 시험, 이미지 파이프라인, 매체 검증은 모두 초록이었다.

회수한 카드의 journal에서 원인이 나왔다.

```text
[7.96] recover-release.sh: File "/opt/rosy/native-runtime/native_release.py", line 26
         from signing import sha256_file, verify_release_files
       ModuleNotFoundError: No module named 'signing'
[8.01] Dependency failed for rosy-core.service - ROSY native CORE runtime.
[8.01] Dependency failed for rosy-runtime.target
```

`deploy/robot/native/native_release.py`는 이렇게 모듈을 찾는다.

```python
RELEASE_TOOLS = Path(__file__).resolve().parents[2] / "release"
```

- 저장소 `deploy/robot/native/`에서는 `deploy/release`라서 성공한다.
- 설치 위치 `/opt/rosy/native-runtime/`에서는 `/opt/release`라서 실패한다.
- 저장소 시험은 저장소 경로로 import하고, `verify-mounted-image.py`는 파일 존재만 확인했다.
  그래서 어느 단계도 이 결함을 볼 수 없었다.

같은 부팅에서 가시성 결함도 함께 드러났다.

- 첫 부팅은 `/etc/hostname`만 쓰고 실행 중 호스트 이름을 바꾸지 않았다(avahi: `ubuntu.local`).
- 이미지에 운영자 계정·키가 없고 cloud-init 기본이 `ssh_pwauth: false`였다.
- 사람이 볼 부팅 신호(부저, LCD, LED)가 없었다.

그 결과 **실패를 알아내는 유일한 방법이 카드 회수**였다.

## Guidance

1. **설치 배치를 재현해 실행한다.** 이미지나 장치로 복사되는 스크립트는 저장소 경로가 아니라
   `build-native-payload.sh`가 만드는 것과 같은 트리(임시 디렉터리 `<tmp>/opt/rosy/native-runtime/`)에 복사한 뒤
   실행하는 계약 시험을 둔다. import와 `--help`, dry-run이 거기서 성공해야 한다.
2. **마운트된 이미지 안에서 진입점을 실행한다.** 파일 존재·해시 검증은 필요하지만 충분하지 않다.
   ARM64 chroot에서 복구 dry-run과 첫 부팅 스크립트를 실제로 돌린다.
3. **`__file__` 기준 상대 경로 탐색을 설치 경계에 두지 않는다.** 필요한 형제 모듈은 함께 설치하고,
   스크립트 자신의 디렉터리부터 찾는다.
4. **장비 없이 카드만으로 진단할 길을 미리 만든다.** Windows에서 USB SD 리더에는 `wsl --mount`가
   통하지 않고(`Wsl/Service/AttachDisk/MountDisk/0x8007000f`), 실패하면 디스크가 오프라인으로 남는다
   (재장착하면 복구된다). 이번에 동작한 경로는 다음과 같다.
   - 관리자 권한으로 `\\.\PhysicalDriveN`을 **읽기 전용**으로 연다(1 MiB 정렬 캐시 래퍼).
   - 순수 Python ext4 파서(`pip install ext4`)로 파티션 오프셋(`Get-Partition`의 `Offset`)에서
     필요한 파일만 꺼낸다. 대상은 `/var/lib/rosy/provisioning`, `/etc/rosy`, `/etc/systemd/system`,
     `/var/log/journal`이다.
   - `NetworkManager/system-connections`는 PSK가 들어 있으므로 읽지 않는다.
   - WSL에서 `journalctl -D <journal-dir> -u <unit>`으로 읽는다. `--file`을 여러 파일에 한 번에 주면
     "Extraneous arguments"로 실패한다.
5. **부팅 가시성은 기능으로 취급한다.** 실제 호스트 이름 적용, 카드별 운영자 공개키, CORE 밖의 부팅
   상태 표시(보드 LED, 콘솔 배너, mDNS)가 없으면 다음 실패도 똑같이 카드 회수로만 보인다.

## Why This Matters

실기 한 번의 부팅 실패가 카드 회수, 관리자 권한 추출, 오프라인 journal 분석까지 이어졌다. 원인
한 줄은 저장소 시험이 설치 배치를 한 번만 흉내 냈어도 잡혔다. 매체 무결성(readback `verified`)과
서명 검증이 완벽해도 "설치된 코드가 그 위치에서 실행된다"는 사실은 증명하지 않는다.

## When to Apply

- `deploy/robot/native`, `deploy/image/first-boot`, Host Agent처럼 저장소 밖 경로에서 실행되는
  도구를 추가하거나 옮길 때
- ARTIFACT gate를 GO로 올리기 전
- 실기 부팅이 "조용히" 실패했을 때(소리·화면·네트워크 응답 없음)

## Examples

설치 배치 재현 시험의 뼈대(D-174 계획 Task 1, 구현 대기):

```python
def test_recovery_runs_from_installed_layout(tmp_path):
    runtime = tmp_path / "opt/rosy/native-runtime"
    shutil.copytree(ROOT / "deploy/robot/native", runtime)
    # build-native-payload.sh와 같은 방식으로 설치하되 저장소 경로는 쓰지 않는다
    completed = subprocess.run([sys.executable, runtime / "native_release.py", "--help"],
                               cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
```

## Related

- ADR: `docs/adr/D-174-first-boot-defects-and-boot-indicator.md`, `docs/adr/D-173-first-pinky-card-from-merged-release.md`
- 계획: `docs/plans/2026-09-22-pinky-first-boot-fixes.md`
- 같은 부류의 교훈: `sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md`,
  `inability-to-check-recorded-as-clean-result.md`
