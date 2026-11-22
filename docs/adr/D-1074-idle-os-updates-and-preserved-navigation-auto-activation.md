## D-1074 IDLE 상태 OS 업데이트 허용 및 업데이트 이전 항법 승인 존중·자동 활성화

**Status:** Accepted (2026-11-23, 사용자 지시). 관련 결정: [D-986](D-986-navigation-reapproval-after-release-change.md) · [D-1005](D-1005-sealed-navigation-approval-measured-speeds.md) · [D-1046](D-1046-os-update-host-idle-admission.md).

### Context

- 사용자 요청: Pinky가 주행/작업(`NAVIGATION`, trip, docking 등) 중에는 OS 업데이트를 차단하고 `IDLE` 상태일 때만 업데이트를 진행하도록 유지하되, 업데이트 이전에 유효하게 봉인된 G4 항법 승인을 릴리즈·OS 변경 뒤에도 그대로 존중하여 항법(`rosy-navigation.service`)이 자동으로 활성화되도록 개선하고, 구버전 OS(`2026.10.29-001` 등)를 최신 OS로 열어 배포한다.
- 기존 `os_update_policy.py`는 봉인된 `/etc/rosy/approvals/{hardware,navigation}.approved`가 있으면 영구 `OS update deferred`로 차단했고, `os_update_controller.source_health()`는 `rosy-io.service`만 허용해 `rosy-navigation.service`가 뜬 상태에서 `IDLE` 전환 후 OS 업데이트를 막았다.
- 기존 `mapping_approval.check()`는 릴리즈 간 `motion_fingerprint`가 조금이라도 달라지거나 구형 마커에 지문이 없으면 재측정을 강제했고, 페이로드 전환(`native_release.activate`)·부팅(`rosy-nav-reapprove.timer` 4분 지연)도 기존 항법 실행 상태나 공유 p6 백업을 이어받아 자동 활성화하지 못했다.
- 실기(`rosy-pinky-b8xy`, `rosy-pinky-y8xs`) 프리플라이트 결과 ① 장기 가동 후 early-boot journald 로테이션 시 `os_update_watchdog.py`의 `OS_WATCHDOG_HOLD` 거짓 거부, ② 물리 디스크 끝으로 백업 GPT가 재배치된 32.04 GB SD 카드(`y8xs`)에서 `os_media.py`의 `OS_MEDIA_HOLD` 거짓 거부를 함께 확인했다.

### Decision

| 항목 | 결정 |
|---|---|
| `IDLE` 전용 OS 업데이트·승인 차단 해제 | `os_update_policy._Policy._controls()`에서 `_sealed(current)` 차단을 제거하고, `source_health()`는 `rosy-core.service`와 활성 모션 유닛(`rosy-io.service` 또는 `zz-rosy-os-guard.conf`가 적용된 `rosy-navigation.service`)을 모두 허용한다. `IDLE`·무주행·배터리·estop·claim·홀드 검사는 그대로 유지한다. |
| 승인 백업·존중·자동 활성화 | `mapping_approval`이 `/var/lib/rosy-device/approvals`(p6 공유 파티션)에 검증된 G4 승인·원시 증거를 미러링·복원하고, `os_update_controller.start()`도 슬롯 전환 전 백업을 보장한다. `mapping_approval.check()`는 `robot_number`·원시 증거 무결성·번들 다이제스트 검증을 유지한 채 릴리즈/OS 지문이 달라진 기존 승인도 존중한다(`fingerprint_changed` 표시). `native_release.activate()`와 `auto_update_apply.py`는 업데이트 직전 `rosy-navigation.service`가 실행 중이었으면 전환 후 재기동·헬스 검증하고, `rosy-nav-reapprove`는 부팅 30초(`OnBootSec=30s`) 후 공유 승인 복원 및 IDLE·비점유·OS가드 통과 시 1회 자동 기동한다. |
| 실기 워치독·GPT 수정 | `os_update_watchdog.py`는 `--grep=watchdog|Watchdog`가 빈 회전 결과(`rc in (0,1)`, 무오류)이고 live firmware/cmdline/sysfs/PID1 `systemctl show`가 모두 일치하면 `--lines=+1 _PID=1`의 `__MONOTONIC_TIMESTAMP > 10_000_000`으로 회전 여부를 확인한다. `os_media.py`는 `os-media.json` 크기 기준 실패 시 실제 물리 디스크 크기의 백업 GPT까지 대조해 파티션·GUID·`provision_role` 완전 일치 시 허용한다. |
| OS 롤아웃 개방 자동화 | `os_bundle.update_rollout --canary`와 `publish_os_release.open_rollout`/`open_release`, `robot_cd.py` `os_auto_rollout`(기본 꺼짐)·`robot_cd_os.py` `stage_timeout=7200`으로 빌드 후 즉시 개방 롤아웃을 지원한다. |

### Consequences & Invariants

- `robot_number`, hardware 모드·구동 활성 검증, G4 원시 증거 속도·거리·정지 지연 한계 검증, OS 업데이트 `IDLE` 게이트 및 `os_motion_guard` 드라이브 차단은 약화하지 않는다.
- 이미 동결된 `2026.10.29-002` OS 이미지가 실린 `y8xs`처럼 동결 `os_media`가 재배치 백업 GPT를 거부하는 기체는 OTA 점프가 불가능하므로, 페이로드·승인 백업 반영 후 신규 이미지 1회 재플래싱이 필요하다.
