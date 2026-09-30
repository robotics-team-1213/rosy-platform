## D-385 페이로드 릴리스를 올리면 이미지 계층(native-runtime·유닛·udev·modprobe)도 활성 릴리스 사본으로 맞춘다

**Status:** Accepted (2026-09-30, 2026-10-01 독립 리뷰 두 차례 반영 개정; 호스트 시험만, 실기 검증은 2026-10-02 예정). D-225(페이로드 릴리스)를 넓힌다. 이미지 안의 `activate-release.sh`·`native_release.py`는 바꾸지 않는다.

**번호:** 작업 중에는 D-375로 불렀다. D-375(예약)·D-382·D-383이 차례로 다른 세션에 먼저 쓰였고 D-384는 예약돼 있어 D-385가 됐다. 브랜치 `feat/release-image-layer-sync`의 앞선 커밋 메시지는 D-375(f05858af, 4859bce0, 6c5ee9bb) 또는 D-383(6e57c35c 이후)이라고 적혀 있고, 이력은 다시 쓰지 않는다.

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

   대상 경로가 이 네 디렉터리 밖이거나 `/boot`, `/etc/rosy/`, `/usr/local/`, `/lib/modules/`, sudoers·passwd·shadow·group이면 거절한다.
4. **udev·modprobe를 페이로드에 싣는다.** `install-native-runtime.sh`가 `image-layer/udev/`·`image-layer/modprobe/`로 복사한다. 그래서 릴리스 사본과 새 이미지의 `/opt/rosy/native-runtime` 사본이 같다. 메타데이터 이름(`manifest.json`, `SHA256SUMS`, `.sig`)과 심볼릭 링크는 없다.
5. **옛 검증기와 호환한다.** 새 파일은 매니페스트에 올라가므로 지금 로봇이 도는 이미지의 `native_release.py`도 새 페이로드를 받아들여야 한다. 이미지 2026.09.27-010(원본 8b67c909)과 2026.09.30-009(원본 5c0ce600)의 `native_release.py`·`signing.py`를 `git show <sha>:<path>`로 꺼내, bash 없이 순수 파이썬으로 만든 새 페이로드를 그 검증기로 `verify()`하는 호스트 시험을 둔다.
6. **`--dry-run`**은 `{changed, new, unchanged, skipped, removed}`, 영향받는 유닛, 재시작 후보, 밀린 명령을 JSON으로 찍고 아무것도 쓰지 않는다. `systemctl is-active`만 읽는다.
7. **적용**
   - 바꾸거나 지울 파일을 모두 `/var/lib/rosy/image-layer-backup/<UTC 시각>-<release_id>/`(0700)에 원래 경로 그대로 백업하고, `backup-manifest.json`에 경로·상태(`new`·`changed`·`removed`·`restored`)·해시·모드를 적는다.
   - 같은 디렉터리의 임시 파일에 쓰고 fsync, 모드·root 소유를 준 뒤 `os.replace`로 바꾼다. 도중에 실패하면 이미 바꾼 파일은 백업으로 되돌리고 새 파일은 지운다.
   - 유닛이 바뀌면 `systemctl daemon-reload`. 새로 생긴 유닛은 `customize-rootfs.sh`가 enable하는 목록에 있을 때만 enable한다. 그 가운데 `.path`·`.timer`는 `systemctl enable --now`로 바로 시작한다(다음 부팅까지 감시·주기가 멈춰 있지 않게). `.service`·`.target`은 enable만 한다. 규칙이 바뀌면 `udevadm control --reload`.
   - 대상이 심볼릭 링크(`/dev/null`로 mask된 유닛)면 건너뛰고 `skipped`에 적는다. mask를 풀지 않는다.
   - modprobe 변경은 `modprobe_changed`로 알리고 모듈을 다시 올리지 않는다.
8. **끝나지 않은 적용은 다음 실행이 이어서 한다.** 파일을 깐 뒤 명령(daemon-reload·enable·udevadm) 전에 `/var/lib/rosy/image-layer-backup/pending.json`에 밀린 명령, 영향 유닛, 시도 횟수를 적는다. 명령이 모두 성공해야 지우고 매니페스트를 `complete: true`로 바꾼다. 다음 실행은 파일이 모두 같아도 `pending.json`이 있으면 그 명령을 다시 돌리고, 그 영향 유닛을 재시작 후보에 다시 올린다. 드라이런은 `pending`으로 보여 주기만 한다.
   - 밀린 enable 가운데 유닛 파일이 없거나 이번 실행이 지우는 유닛은 버린다. 롤백이 치운 유닛을 영원히 enable하려 들지 않게 한다.
   - 같은 밀린 명령을 3번 시도해도 실패하면 `pending.json`을 `pending.parked-<UTC>.json`으로 옮기고 `pending_parked`로 크게 알린 뒤, 이번 실행의 자기 명령만 돌린다. 한 번 활성화된 뒤의 푸시마다 적용이 같은 곳에서 멈추지 않게 한다.
   - `pending.json`이 깨졌으면 `pending.corrupt-<UTC>.json`으로 옮기고 `pending_quarantined`로 알린 뒤 파일 단위 계획으로 이어 간다(드라이런은 옮기지 않고 알리기만 한다).
9. **롤백 복원.** 동기화는 자기가 한 일을 백업 매니페스트로 안다.
   - **믿는 매니페스트.** 매니페스트는 파일을 바꾸기 전에 `files_applied: false`로 쓰고, 파일 변경이 모두 끝난 직후(명령 전)에 `true`로 바꾼다. 기록 조회는 `files_applied: true`인 매니페스트만 쓴다. 파일 변경 전의 disable 실패나, 설치 실패 뒤 되돌린 실행은 기록으로 남지 않는다. `complete`로 거르지 않는 까닭은 파일은 깔렸고 명령만 실패한 실행도 `complete: false`이기 때문이다. 읽을 수 없는 매니페스트는 건너뛰고 `corrupt_manifests`로 알린다.
   - **기원까지 거슬러 간다.** current 릴리스의 허용 목록이 만들지 않는 경로마다 그 경로의 기록을 최신부터 거슬러 읽는다. 이어지는 `changed`를 지나 `new`를 만나면 그 경로는 동기화가 만든 것이므로 지운다. `restored`·`removed`나 기록의 처음에 닿으면 가장 오래된 `changed`의 백업(동기화 이전 상태)으로 되돌린다. 최신 기록이 `removed`·`restored`면 이미 되돌린 것이므로 손대지 않는다. 그래서 A→C(추가)→D(변경)→B에서 X는 D 백업의 C 사본이 아니라 없음으로 돌아간다.
   - 지금 파일 해시가 최신 기록(마지막 동기화가 깐 것)과 다르면 사람이 손댄 것으로 보고 건드리지 않고 `skipped`에 적는다.
   - 유닛을 지울 때는 먼저 `systemctl disable --now`로 끄고 daemon-reload한다. 이 disable도 되돌림 범위 안에 있다. 뒤이은 설치가 실패하면 파일을 되돌리고, 그 유닛이 enable이었으면 다시 enable, 활성이었으면 다시 start한다.
   - current가 만드는 경로는 current 사본으로 맞추는 일반 동기화가 곧 복원이다.

   지우고 되돌린 파일도 이번 실행의 백업에 먼저 남긴다. 모두 허용 목록 네 디렉터리 안에서만 한다.
10. **재시작 후보에서 빼는 유닛.** `restart_units`는 활성이고 바뀐 유닛 가운데 다음을 뺀다.
    - `.target`
    - `rosy-release-recover.service`·`rosy-sd-provision.service`(rosy-core가 Requires로 묶은 부팅 oneshot이라 재시작하면 CORE가 따라 재시작된다)
    - `rosy-network.service`·`rosy-config.service`(푸시를 돌리는 SSH 연결을 끊을 수 있다)
    - `rosy-first-boot*`

    뺀 유닛은 `next_boot_units`(target은 `active_targets_affected`)로 알리고, 푸시 스크립트는 "다음 부팅에 적용"이라고 찍는다.
11. **`rosy-release-push.ps1`**
    - 푸시: 활성화 → CORE 준비 확인 → 새 릴리스의 스크립트로 드라이런(계획 출력) → 적용 → 적용 결과의 `restart_units` 가운데 `rosy-*.service|path|timer`만 `systemctl restart`하고 찍음 → 재시작했으면 CORE 준비를 다시 확인. `rosy-core`는 활성화 때 옛 유닛 정의로 떴으므로 유닛이 바뀌었으면 다시 재시작한다. `rosy-io` 재시작은 모터를 잠깐 멈추며, 활성화 직후에는 이를 받아들인다.
    - 롤백: 롤백 → 드라이런 → 적용 → 재시작 → CORE 준비 확인. 동기화를 준비 확인보다 **먼저** 한다. N+1의 유닛·스크립트가 N과 맞지 않아 CORE가 준비되지 못해도, 이미지 계층을 N으로 되돌린 뒤에 확인하게 한다. 스크립트는 current(되돌아간 릴리스)의 사본을 먼저 쓰고, 그 릴리스가 D-385 이전이면 previous(방금 떠난 릴리스)의 사본을 쓴다. 원본은 어느 쪽이든 current다. 둘 다 없으면 경고하고 동기화를 건너뛰지만 준비 확인은 한다.
    - `-SkipImageLayerSync`로 끈다(롤백은 롤백 → 준비 확인). `-PrintCommands`는 새 단계를 실행 없이 보여 준다(재시작 단계의 유닛 이름은 자리표시).

### 범위 밖

- `config.txt`·`/boot`, 커널과 모듈, `/usr/local` 파이썬, `/etc/rosy/*`, 사용자·sudoers, 첫 부팅 유닛(`image/first-boot`), journald·tmpfiles 설정.
- 백업 매니페스트에 없는 파일은 지우지 않는다. 이미지가 깐 파일이 나중 릴리스에서 빠져도 `/opt/rosy/native-runtime`·유닛 디렉터리에 그대로 남는다. 동기화가 추가한 파일만 9항으로 치운다.
- 스크립트가 유닛을 재시작하지 않는다. 재시작은 푸시 스크립트가 한다.

### Alternatives

- **이미지의 `activate-release.sh`가 동기화하게 바꾸기** — 이미 굽힌 로봇에는 새 이미지 전까지 닿지 않는다. 문제가 바로 그 로봇들이다.
- **원격에서 rsync/scp로 PC의 저장소 파일을 직접 깔기** — 서명이 덮지 않는 원본이다. 릴리스 사본은 서명·해시로 검증된다.
- **스크립트가 바뀐 유닛을 직접 재시작** — 모터를 멈추는 결정은 운영자 도구가 내려야 한다. 스크립트는 알리기만 한다.
- **native-runtime에서 current에 없는 파일을 모두 지우기** — 이미지가 깐 도구까지 사라질 수 있다. 동기화가 추가했다고 기록한 것만 지운다.
- **롤백 때 마지막 백업 디렉터리를 통째로 되돌리기** — 그 사이 다른 동기화나 손 설치가 있었으면 덮어쓴다. 경로마다 마지막 기록과 지금 해시를 대조한다.
- **밀린 명령 대신 매번 daemon-reload·udevadm을 돌리기** — 멱등성을 잃고, 실패한 enable은 여전히 되풀이되지 않는다.

### Consequences

- 페이로드 푸시 한 번으로 허용 목록의 이미지 계층이 새 이미지와 같아진다. 스킬 6단계의 손 설치는 스크립트가 없거나 허용 목록 밖일 때의 비상 절차로 남는다.
- 영향 유닛 탐지는 유닛 파일이 경로로 부르는 스크립트까지만 본다. 그 스크립트가 import하는 도우미(`rosy_config.py` 등)만 바뀌면 재시작 후보에 오르지 않는다.
- 이 기능이 든 첫 릴리스를 올리기 전까지는 효과가 없다. 그 전 릴리스로 롤백하면 previous의 스크립트가 옛 사본으로 되맞춘다.

### Validation

- 호스트 시험 `test/test_image_layer_sync.py`: 허용 목록이 빌드 스크립트 결과와 같음, 새 이미지는 이미 동기, 드라이런 무기록, 적용·백업·매니페스트, 멱등, 설치 실패 복원, 명령 실패 뒤 재실행이 밀린 명령·재시작 후보를 되살림, 롤백 복원(추가 파일 제거·유닛 disable, 바꾼 파일 되돌림, 손댄 파일은 그대로), 재시작 제외 유닛, `.path`·`.timer` 즉시 시작, current 거절, 서명 불일치 거절, 금지 경로, 옛 릴리스, 서명된 릴리스로 CLI 실행 후 바이트코드 없음, 옛 검증기(8b67c909·5c0ce600)가 새 페이로드를 받아들임. 가짜 루트와 기록용 러너만 쓰고 실제 systemctl·udevadm은 부르지 않는다.
- 2차 리뷰 시험(`test/test_image_layer_sync.py`): 파일 변경 전 disable 실패·설치 실패로 되돌린 매니페스트가 기록을 가리지 않음, 파일은 깔렸고 명령만 실패한 매니페스트는 기록으로 씀, 롤백이 치운 유닛의 밀린 enable을 버림, 밀린 명령 3회 실패 시 보관 후 진행, A→C→D→B 연쇄에서 X 제거, disable 뒤 설치 실패 시 유닛 재enable·재start, 깨진 `pending.json` 격리, 깨진 매니페스트 보고.
- `test/test_release_push_entrypoint.py`: 푸시·롤백 계획의 단계와 순서(롤백은 동기화가 준비 확인 앞), `-SkipImageLayerSync`, 가짜 ssh로 적용 결과의 `rosy-*` 유닛만 재시작, 다음 부팅 유닛 안내, 롤백 대상에 스크립트가 없으면 경고 후 건너뛰고 준비 확인은 함, ASCII 유지.
- 새 방어 각각은 깨뜨려 빨강, 되돌려 초록을 확인한다(`test/AGENTS.md`).
- mask 유닛 건너뛰기와 POSIX 모드 비교 시험은 Windows에서 건너뛰어 CI(Linux)에서만 돈다. 옛 검증기 시험은 그 커밋이 없는 얕은 클론에서 건너뛴다.
- **실기 검증 계획(2026-10-02).** 벤치 로봇 한 대에서:
  1. 이 기능이 든 릴리스를 푸시하고 드라이런 계획을 기록한다.
  2. 적용 결과(백업 디렉터리·매니페스트·명령)를 확인한다.
  3. 재시작된 유닛과 CORE 준비 확인 결과를 기록한다.
  4. `-Rollback`으로 되돌리고, 추가됐던 파일이 치워지고 유닛이 이전 릴리스 사본으로 돌아갔는지, CORE가 준비됐는지 확인한다.

  결과는 `deploy/logs.md`에 남기고 이 ADR의 Status를 갱신한다.

### References

- D-225 페이로드 전용 릴리스, D-174 F1 native-runtime 설치, D-189 D1 복구 유닛 쓰기 범위, D-247 램프 udev·modprobe
- `.claude/skills/rosy-release-push/SKILL.md` 6단계
- 문제 기록: `docs/solutions/workflow-issues/payload-push-leaves-the-image-layer-stale-2026-10-01.md`
