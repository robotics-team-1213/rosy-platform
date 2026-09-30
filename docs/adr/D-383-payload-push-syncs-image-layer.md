## D-383 페이로드 릴리스를 올리면 이미지 계층(native-runtime·유닛·udev·modprobe)도 활성 릴리스 사본으로 맞춘다

**Status:** Accepted (2026-09-30, 호스트 시험만; 실기 실행 대기). D-225(페이로드 릴리스)를 넓힌다. 이미지 안의 `activate-release.sh`·`native_release.py`는 바꾸지 않는다.

### Context

D-225 페이로드 릴리스는 `/opt/rosy/releases/<id>`(`install/`, 릴리스 사본 `deploy/robot/native/`)를 넣고 `/opt/rosy/current`를 옮긴다. 이미지가 릴리스 밖에 깐 것은 그대로다.

- `/etc/systemd/system/rosy-*` 유닛, `/opt/rosy/native-runtime/` 스크립트
- udev 규칙(`deploy/robot/pinky_pro/udev/*.rules`)과 modprobe 옵션(`deploy/robot/pinky_pro/modprobe/*`). `build-native-payload.sh`가 이 둘을 `image-overlay/`에만 넣어서 페이로드에는 아예 없다.

그래서 이미 굽힌 로봇은 새 이미지와 조용히 어긋난다. 2026-09-30 이미지 2026.09.27-010 로봇에 2026.09.30-008을 올릴 때 `rosy-io.service`(`enable_ir:=true`), `rosy-navigation.service`(새 ExecCondition), 새 `mapping_approval.py`를 손으로 깔아야 했다(`rosy-release-push` 스킬 6단계).

제약: 오래된 로봇은 이미지에 든 옛 `activate-release.sh`·`native_release.py`를 돈다. 새 동작은 PC 쪽(`rosy-release-push.ps1`)이 새 릴리스 안에 든 스크립트를 부르는 방식이어야 한다.

### Decision

1. **동기화 스크립트는 릴리스에 싣는다.** `deploy/robot/pinky_pro/native/sync-image-layer.py`. 릴리스에서는 `/opt/rosy/releases/<id>/deploy/robot/native/sync-image-layer.py`이고, `sudo -n python3 -B`로 돈다.
2. **원본은 활성 릴리스뿐이다.** `/opt/rosy/current`가 심볼릭 링크이고 `/opt/rosy/releases/<YYYY.MM.DD-NNN>`를 가리키며, 그 릴리스가 신뢰 키로 `native_release.py verify()`를 통과해야 한다. 아니면 아무것도 쓰지 않고 거절한다. 도는 동안 `native_release.py`와 같은 잠금(`/var/lib/rosy/releases/native-release.lock`)을 잡아 current가 옮겨지지 않게 한다.
3. **허용 목록**은 새 이미지가 까는 것과 같다(시험이 두 빌드 스크립트와 대조한다).

   | 원본(릴리스 `deploy/robot/native/`) | 대상 | 모드 |
   |---|---|---|
   | 모든 파일(`install-native-runtime.sh` 결과 그대로, `image-layer/` 포함) | `/opt/rosy/native-runtime/` | 원본 실행 비트면 0755, 아니면 0644 |
   | `build-native-payload.sh`가 `/etc/systemd/system`에 복사하는 18개 유닛 | `/etc/systemd/system/` | 0644 |
   | `image-layer/udev/*.rules` | `/etc/udev/rules.d/` | 0644 |
   | `image-layer/modprobe/*.conf` | `/etc/modprobe.d/` | 0644 |

   대상 경로는 이 네 디렉터리 밖이거나 `/boot`, `/etc/rosy/`, `/usr/local/`, `/lib/modules/`, sudoers·passwd·shadow·group이면 거절한다. 첫 부팅 유닛(`image/first-boot`), journald·tmpfiles 설정, `/etc/rosy/*`, `config.txt`, 커널 모듈, `/usr/local` 파이썬은 다루지 않는다. 대상 파일에 없는 여분 파일은 지우지 않는다.
4. **udev·modprobe를 페이로드에 싣는다.** `install-native-runtime.sh`가 `image-layer/udev/`·`image-layer/modprobe/`로 복사한다. 그래서 릴리스 사본과 새 이미지의 `/opt/rosy/native-runtime` 사본이 같다. 메타데이터 이름(`manifest.json`, `SHA256SUMS`, `.sig`)과 심볼릭 링크는 없다. 새 파일은 매니페스트에 올라가므로 옛 `native_release.py`의 인벤토리 검사도 통과한다.
5. **`--dry-run`**은 `{changed, new, unchanged, skipped}`와 영향받는 유닛·재시작 후보를 JSON으로 찍고 아무것도 쓰지 않는다. `systemctl is-active`만 읽는다.
6. **적용**
   - 바꿀 파일을 모두 `/var/lib/rosy/image-layer-backup/<UTC 시각>-<release_id>/`(0700)에 원래 경로 그대로 백업하고, `backup-manifest.json`에 경로·상태·해시·모드를 적는다.
   - 같은 디렉터리의 임시 파일에 쓰고 fsync, 모드·root 소유를 준 뒤 `os.replace`로 바꾼다. 도중에 실패하면 이미 바꾼 파일은 백업으로 되돌리고 새 파일은 지운다.
   - 유닛이 바뀌면 `systemctl daemon-reload`. 새로 생긴 유닛은 `customize-rootfs.sh`가 enable하는 목록에 있을 때만 `systemctl enable`(`--now` 없음). 규칙이 바뀌면 `udevadm control --reload`.
   - 대상이 심볼릭 링크(`/dev/null`로 mask된 유닛)면 건너뛰고 `skipped`에 적는다. mask를 풀지 않는다.
   - 유닛을 재시작하지 않는다. `restart_units`에 활성 유닛 가운데 유닛 파일이 바뀌었거나, 유닛 파일이 부르는 `/opt/rosy/native-runtime/<파일>`이 바뀐 것을 적는다(target은 `active_targets_affected`로 따로 적는다). modprobe 변경은 `modprobe_changed`로 알리고 모듈을 다시 올리지 않는다.
   - 멱등이다. 두 번째 실행은 바꿀 것이 없고 백업·명령도 없다.
7. **`rosy-release-push.ps1`**
   - 활성화와 CORE 준비 확인이 끝나면 새 릴리스의 스크립트로 드라이런(계획 출력), 적용을 차례로 한다.
   - 적용 결과의 `restart_units` 가운데 `rosy-*.service|path|timer`만 `systemctl restart`하고 무엇을 재시작했는지 찍는다. 재시작했으면 CORE 준비를 다시 확인한다. `rosy-core`는 활성화 때 재시작됐지만 옛 유닛 정의로 떴으므로, 유닛이 바뀌었으면 다시 재시작한다. `rosy-io` 재시작은 모터를 잠깐 멈추며, 활성화 직후에는 이를 받아들인다.
   - `-Rollback`도 롤백 뒤 같은 단계를 돈다. 스크립트는 current(되돌아간 릴리스)의 사본을 먼저 쓰고, 그 릴리스가 D-383 이전이면 previous(방금 떠난 릴리스)의 사본을 쓴다. 원본은 어느 쪽이든 current다. 둘 다 없으면 경고하고 건너뛴다.
   - `-SkipImageLayerSync`로 끈다. `-PrintCommands`는 새 단계를 실행 없이 보여 준다(재시작 단계의 유닛 이름은 자리표시).

### Alternatives

- **이미지의 `activate-release.sh`가 동기화하게 바꾸기** — 이미 굽힌 로봇에는 새 이미지 전까지 닿지 않는다. 문제가 바로 그 로봇들이다.
- **원격에서 rsync/scp로 PC의 저장소 파일을 직접 깔기** — 서명이 덮지 않는 원본이다. 릴리스 사본은 서명·해시로 검증된다.
- **스크립트가 바뀐 유닛을 직접 재시작** — 모터를 멈추는 결정은 운영자 도구가 내려야 한다. 스크립트는 알리기만 한다.
- **native-runtime에서 릴리스에 없는 파일 지우기** — 롤백이 옛 릴리스로 가면 새 도구(이 스크립트 포함)가 사라진다. 여분은 남긴다.

### Consequences

- 페이로드 푸시 한 번으로 허용 목록의 이미지 계층이 새 이미지와 같아진다. 스킬 6단계의 손 설치는 스크립트가 없거나 허용 목록 밖일 때의 비상 절차로 남는다.
- 영향 유닛 탐지는 유닛 파일이 경로로 부르는 스크립트까지만 본다. 그 스크립트가 import하는 도우미(`rosy_config.py` 등)만 바뀌면 재시작 후보에 오르지 않는다.
- 이 기능이 든 첫 릴리스를 올리기 전까지는 효과가 없다. 그 전 릴리스로 롤백하면 previous의 스크립트가 옛 사본으로 되맞춘다.

### Validation

- 호스트 시험 `test/test_image_layer_sync.py`: 허용 목록이 `build-native-payload.sh`·`customize-rootfs.sh`·`install-native-runtime.sh` 결과와 같음, 새 이미지는 이미 동기, 드라이런 무기록, 적용·백업·매니페스트, 멱등, 설치 실패 복원, current 거절(링크 아님·저장소 밖), 서명 불일치 거절, 금지 경로, 옛 릴리스(`image-layer/` 없음), 서명된 릴리스로 CLI 실행 후 릴리스에 바이트코드 없음, 페이로드 매니페스트에 udev·modprobe 포함과 `verify()` 통과. 가짜 루트와 기록용 러너만 쓰고 실제 systemctl·udevadm은 부르지 않는다.
- `test/test_release_push_entrypoint.py`: 푸시·롤백 계획의 새 단계, `-SkipImageLayerSync`, 가짜 ssh로 적용 결과의 `rosy-*` 유닛만 재시작하고 CORE 준비를 두 번 확인, 롤백 대상에 스크립트가 없으면 경고 후 건너뜀, ASCII 유지.
- 새 방어 각각은 깨뜨려 빨강, 되돌려 초록을 확인했다(`test/AGENTS.md`).
- **실기 미검증.** mask 유닛 건너뛰기와 POSIX 모드 비교 시험은 Windows에서 건너뛰어 CI(Linux)에서만 돈다. 실제 로봇에서 드라이런→적용→재시작을 한 번 돌려 확인해야 한다.

### References

- D-225 페이로드 전용 릴리스, D-174 F1 native-runtime 설치, D-189 D1 복구 유닛 쓰기 범위, D-247 램프 udev·modprobe
- `.claude/skills/rosy-release-push/SKILL.md` 6단계
- 문제 기록: `docs/solutions/workflow-issues/payload-push-leaves-the-image-layer-stale-2026-10-01.md` (작업 중에는 D-375로 불렀으나 번호가 겹쳐 D-383이 됐다)
