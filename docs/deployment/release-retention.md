# ROSY 릴리스 보존과 저장소 예산

- **Document ID:** ROSY-DEPLOY-RETENTION-001
- **Status:** v1
- **Related:** `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md` §5/§9,
  `deploy/robot/pinky_pro/release/layout.py`, `deploy/robot/pinky_pro/release/updater.py`

## 1. 왜 예산이 필요한가

장비는 SD 카드 하나로 동작한다. 릴리스, config/data generation, 백업, 이벤트,
맵, 컨테이너 이미지가 모두 같은 카드에 쌓인다. 여기서 공간이 떨어지면 그 결과는
"디스크 가득 참" 이 아니라 **업데이트 실패 또는 롤백 불능**이다. 새 릴리스를
staging 할 공간이 없으면 업데이트가 시작조차 못 하고, 이전 릴리스를 지워 공간을
만들면 롤백 대상이 사라진다.

그래서 보존 정책은 청소 규칙이 아니라 복구 가능성의 일부다.

## 2. 예산 (32 GB SD 기준)

| 항목 | 예산 | 초과 시 |
|---|---|---|
| OS + 기본 패키지 | ~4 GB | 이미지 빌드 실패로 드러남 |
| 릴리스 디렉터리 `/opt/rosy/releases` | 릴리스당 ~200 MB × 3 = 600 MB | 오래된 릴리스부터 정리 (§3) |
| 컨테이너 이미지 | ARM64 candidate baseline: `rosy-core` ~1.63 GB + `rosy-io` ~3.50 GB; 릴리스당 최대 2 세트 = ~10.26 GB | 참조되지 않는 digest만 prune (§4) |
| config/data generation | generation당 ~10 MB × 6 = 60 MB | 릴리스와 함께 정리 |
| 백업 `/var/lib/rosy/backups` | 백업당 ~50 MB, 최대 3개 = 150 MB | 가장 오래된 백업 삭제 |
| 이벤트 `/var/lib/rosy/events` | 500 MB 상한 | 오래된 이벤트부터 회전 |
| 맵 `/var/lib/rosy/maps` | 1 GB 상한 | 삭제하지 않고 경고만 — 맵은 사용자 자산이다 |
| staging `/var/cache/rosy/releases` | 업데이트 중 최대 1 세트 ~3 GB | 활성화 후 즉시 삭제 |
| 여유(상시) | 4 GB | §5의 진입 조건으로 보호 |

위 항목의 합은 ARM64 candidate 이미지 크기를 반영하면 약 **19.6 GB**이고,
상시 확보할 여유 4 GB를 더하면 약 **23.6 GB**다. 32 GB 카드(포맷 후
실사용 약 29 GB)에서는 약 5.4 GB만 남으므로, 실제 릴리스 압축 크기를
확정하기 전에는 64 GB를 기본 Device 매체로 선택한다.

16 GB 카드는 성립하지 않는다. 보존 릴리스를 3개에서 2개로 줄여도 릴리스 디렉터리
200 MB와 이미지 한 세트 2.7 GB만 회수되어 약 15.8 GB가 필요하고, 포맷 후 실사용
용량(약 14.5 GB)을 이미 넘는다. **v1의 검증 기준은 64 GB다.** 32 GB는
실제 릴리스 OCI 압축 크기와 보존 정책을 측정한 뒤에만 허용한다. 64 GB면
§5의 업데이트 진입 조건을 여유 있게 만족한다.

숫자 중 컨테이너 이미지 크기는 현재 `deploy/robot/pinky_pro/Dockerfile`의 `ros:jazzy-ros-base`
기반 추정이며, WP-6에서 실제 이미지를 빌드한 뒤 실측으로 교체해야 한다. 나머지는
상한으로 강제할 값이다.

## 3. 릴리스 보존

기본 정책은 **최근 정상 릴리스 3개**를 유지하는 것이다. 여기에 더해:

- 어떤 activation record가 가리키는 릴리스는 나이와 무관하게 보존한다.
  현재(current)와 이전(previous)이 최소 조건이다.
- 최초 factory recovery 이미지는 별도 보관하며 이 정책의 대상이 아니다.

`deploy/robot/pinky_pro/release/updater.py`의 `releases_to_keep(installed, *, keep_last, protected)`가
이 규칙을 구현한다. `protected`가 비어 있지 않으면 `keep_last`를 초과해서라도
유지한다 — **롤백 대상 릴리스를 지우는 것은 복구 가능한 실패를 현장 방문으로
바꾸는 일이다.**

## 4. 컨테이너 이미지 정리 — prune 금지 규칙

`docker image prune`은 릴리스 개념을 모른다. 사용 중이 아닌 이미지를 지우는데,
"사용 중" 의 정의가 *실행 중인 컨테이너* 이기 때문에 **이전 릴리스의 이미지는
정지 상태라 prune 대상이 된다.** 그 상태에서 health 실패 롤백이 걸리면 이전
릴리스를 기동할 이미지가 없다.

규칙: **어떤 activation record가 참조하는 릴리스의 manifest에 적힌 digest는
절대 prune하지 않는다.**

`prunable_image_digests(all_digests, *, activation_records, manifests_by_release)`가
이를 계산한다. 두 가지 보수적 동작이 있다.

- 활성 릴리스의 manifest를 읽을 수 없으면 **아무것도 prune하지 않는다.** 살아있는
  릴리스가 무엇을 필요로 하는지 모르는 상태는 삭제할 이유가 아니라 삭제하지 않을
  이유다.
- `rosy_io`는 `rosy-motor`와 `rosy-io` 두 서비스가 공유하는 단일 이미지이고,
  두 릴리스가 같은 digest를 가리킬 수 있다. 어느 한쪽이 참조하면 보호된다.

장비에서 `docker image prune -a`를 그대로 실행하는 운영 절차를 만들지 말 것.
정리는 위 함수가 계산한 목록에 대해서만 수행한다.

## 5. 여유 공간과 업데이트 진입 조건

업데이트는 시작 전에 여유 공간을 확인해야 한다. staging에 필요한 공간
(번들 크기 + 압축 해제분)을 확보하지 못하면 **업데이트를 시작하지 않고 거부한다.**
절반쯤 풀린 staging을 남기고 실패하는 것보다 시작하지 않는 편이 낫다.

- 진입 조건: 여유 공간 ≥ 번들 크기 × 2.5 + 1 GB.
  ~3 GB 번들이면 8.5 GB가 필요하다. §2의 예산이 32 GB 카드에서 남기는 약 10 GB로
  충족되며, 이 숫자가 최소 용량을 32 GB로 정한 이유다. 16 GB 카드에서는 이 조건을
  만족시킬 수 없다.
- 미달 시: `UPDATE REJECTED`, 사유는 필요/가용 용량을 숫자로 표시
- 활성화 성공 직후 staging 디렉터리를 삭제하고, 그 다음에 보존 정책(§3, §4)을 적용

정리 순서가 중요하다. **활성화가 끝나기 전에는 어떤 릴리스도 지우지 않는다.**
활성화 도중의 정리는 롤백 대상을 지울 수 있다.

## 6. 대시보드 표시

설계 §9.4가 요구하는 대로 다음을 표시한다.

- 백업 범위와 크기, 보존 개수
- 현재 여유 공간과 업데이트 진입 조건 충족 여부
- 보존 중인 릴리스 목록과 각각이 current/previous인지
- 정리로 삭제된 항목과 그 사유

## 7. 구현 상태

| 정책 | 구현 | 테스트 |
|---|---|---|
| §3 릴리스 보존 | `updater.releases_to_keep` | 있음 |
| §4 prune 금지 | `updater.prunable_image_digests` | 있음 |
| §5 여유 공간 진입 조건 | `storage.check_update_headroom`, `Updater.check_headroom` | 있음 |
| §5 활성화 후 staging 삭제 | `storage.clear_staging`, `Updater._reclaim` | 있음 |
| 이벤트 상한 회전 | `storage.rotate_directory` | 있음 |
| 백업 보존 | `storage.prune_backups` | 있음 |
| 맵 상한 | **경고만** — `storage.reclaim`이 측정하고 삭제하지 않는다 | 있음 |
| §6 대시보드 표시 | **미구현** (WP-5) | — |

세 가지가 설계 판단이며 테스트로 고정되어 있다.

**정리는 활성화가 끝난 뒤에만 한다.** `_reclaim`은 성공 경로에서만 호출된다.
롤백 경로에서 부르면 운영자가 올려둔 staging 번들을 지우게 되고, 그건 방금
실패한 업데이트를 다시 시도할 수단을 없애는 일이다.

**맵은 어떤 정리에서도 삭제하지 않는다.** 이벤트와 백업은 다시 생기지만 측량
결과는 그렇지 않다. 상한을 넘으면 숫자와 함께 경고하고 그친다 — 조용히 측량을
지우는 장비가 공간이 부족하다고 말하는 장비보다 나쁘다.

**정리 실패가 업데이트 실패가 되지 않는다.** `_reclaim`은 활성화가 이미 성공한
뒤에 돌므로, 여기서 나는 문제는 저장소 문제이지 업데이트 문제가 아니다.

여유 공간 거부는 두 숫자를 함께 낸다 — "공간 부족"은 행동 가능한 정보가 아니고
"8.5 GiB 필요, 6.0 GiB 가용"은 어떤 카드를 가져와야 하는지 알려준다.
