## D-881 A/B 이미지의 기체 상태와 슬롯별 적용 기록을 분리한다

**Status:** Proposed

### Context

새 ROSY Pinky 이미지와 전체 OS 자동 업데이트에는 root A/B 전환 뒤에도 기체 identity·네트워크·인증 변경을 보존하는 data 파티션이 필요하다. 기존 updater는 config/Hold와 applying/state를 한 경로에 둔다. firstboot는 complete가 있으면 돌아오므로, 공통 완료 기록만 공유하면 새 root 설정이 누락된다. 반대로 초기 설정 snapshot을 반복 투영하면 이후 Wi-Fi 변경이나 SSH revoke가 사라질 수 있다.

### Decision

1. 각 root의 `/opt/rosy`, `/var/lib/rosy/releases`, `/var/lib/rosy/updates`와 image-layer inverse는 슬롯에 남긴다. applying/staged/status/history·activation journal을 다른 root에 replay하지 않는다.
2. 공통 data는 `/var/lib/rosy-device`에 둔다. updater config/Hold만 공통 policy 경로에 직접 접근한다. atomic replace/unlink를 깨뜨리는 개별 파일 bind mount는 사용하지 않는다.
3. image-owned `/etc/rosy/os-slot.json`과 `rosy.os_layout=ab-v1` kernel marker는 함께 필요하다. descriptor schema/state_schema·slot·root/data/provision PARTUUID는 strict하게 검증한다. D-879의 파티션 역할에 따라 root A는4, root B는5, 공통 data는6, provision boot_a는2이며 실제 sysfs 파티션 번호와 동일 physical disk parent를 확인한다. 둘 다 없는 legacy만 기존 경로를 사용하며 AB 오류에서 legacy로 fallback하지 않는다.
4. 두 admission 단계를 둔다. storage 단계는 root/data/provision의 실제 device·mount root/subpath·옵션과 공통 schema를 검사한다. firstboot 초기화/투영 뒤 state 단계가 boot/slot/descriptor/canonical generation과 결속된 root projection을 확인하고 payload recovery·updater·runtime을 허용한다. 소비자 admission에서 mount를 다시 검사한다.
5. builder가 명시적으로 만든 FACTORY_EMPTY, INITIALIZING, COMMITTED, PROJECTED, NEW_DEVICE_SETUP, HOLD를 구분한다. 누락·부패·미지원 schema를 초기 공장 상태로 추정하지 않는다. `Requires`와 `After`를 통해 실제 boot gate를 연결하고 NetworkManager·SSH socket·tailscaled의 선행 활성화와 dependency cycle을 시험한다.
6. mutable CORE HOME·NM profile·SSH key/registry는 기존 소유자가 공유 정본을 계속 갱신한다. 남는 privileged device 설정은 canonical generation commit 경로를 사용한다. 삭제·revoke는 A→B→A에서 보존되며 firstboot snapshot으로 되살리지 않는다. 전체 `/etc`·계정 DB·payload code는 공유하지 않는다.
7. 기존 firstboot `_stage_new_device()`의 network-assisted handoff를 유지한다. 검증된 site/operator 접근을 보존하되 이전 robot의 CORE/DDS/API/Fleet 실행 권한은 열지 않는다. 이미 provisioned된 A root를 다른 board로 옮긴 반례를 시험한다(D-746의 SD 교체/reimage 정책도 참조).
8. canonical generation의 file contents/mode와 directory entries를 durable하게 게시한 뒤, 해당 generation을 참조하는 completion을 durable commit한다. 그 뒤에만 provision bundle을 삭제하고 parent directory를 fsync한다. 예외 주입뿐 아니라 rename/directory persistence 손실·재정렬을 모델링하고, 실제 powercut 수용은 별도로 남긴다.
9. boot_a의 provision PARTUUID mount를 양 root가 사용한다. factory native signature는 동일 release/checksum에만 결속한다. SSH host keys는 factory에 넣지 않으며 전용 공통 저장소·ordering으로 host identity를 보존한다.

### Ownership and existing decisions

| 기준 | 관계 |
|---|---|
| D-161 | Ubuntu/native systemd 제품 경로를 유지하고 런타임 의존성을 추가하지 않는다 |
| D-225 / D-387 / D-412 | 기존 payload 업데이트·기존 recovery와 이후 전체 OS 슬롯 전환의 상태 범위를 나눈다. 이 ADR만으로 OS engine이 구현된 것은 아니다 |
| D-427 | 배포/host owner 안에서 storage·firstboot를 다룬다. 폴더 위치로 robot command 권한을 늘리지 않는다 |
| D-429 | image-owned descriptor, 설치 closure, payload-owned runtime의 책임을 구분한다 |
| D-430 | admission 실패는 기존 runtime gate를 닫으며 CORE의 최종 Base 명령 권한을 보존한다. OMX 권한을 변경하지 않는다 |

### Alternatives and consequences

`/var/lib/rosy` 전체 공유는 다른 root의 journal/inverse를 재생하므로 기각한다. 개별 config 파일 bind는 atomic replace/unlink와 맞지 않는다. 최초 credential snapshot 재생은 이후 rotation/revoke를 잃는다. 하나의 ready gate는 초기화에 필요한 storage와 이미 projection된 root를 구분하지 못하므로 두 단계로 나눈다.

writer·reader·설치·unit ordering을 함께 변경해야 하므로 단순 path helper 추가로 완료하지 않는다. 실제 updater/firstboot/config/network/auth/SSH 소비자의 A→B→A와 installed-layout 회귀를 요구한다. source 시험은 native ARM64 이미지, 실물 mount/부팅, OS trial/fallback 또는 powercut 수용을 대신하지 않는다. media v2 production BUILD_GO 차단은 전체 builder/backend 수용 전 유지한다.
