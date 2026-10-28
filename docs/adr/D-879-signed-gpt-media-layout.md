## D-879 서명된 GPT A/B 이미지의 파티션 역할을 SD 도구가 함께 검증한다

**Status:** Proposed

### Context

사용자는 기체가 연결되지 않은 상태에서 새 ROSY 이미지를 준비하고, 이후 OS 전체를 자동 갱신할 수 있는 배포 구조를 요청했다.
D-387 P4의 bootstrap/boot A/boot B/root A/root B/data 배치를 SD 도구가 알아야 한다.
현재 image manifest v1과 readback은 MBR의 첫 FAT32 파티션을 전제로 한다.
GPT 이미지를 기록하면서 그 선택 규칙을 유지하면 다른 boot 파티션에 개인화 정보를 쓸 수 있다.

### Decision

1. **기존 v1 MBR 경로를 유지하고, 실험용 image manifest v2에 `layout`을 추가한다.**
   기존 release identity와 image filename/SHA 검증은 유지한다. payload manifest schema를 늘리지 않는다.
   v2 도구 수용은 native ARM64 이미지·부팅·OS 업데이트의 GO가 아니다.
   완성된 builder/firstboot/OS 슬롯 엔진을 검증하기 전 v2는 production `BUILD_GO`를 받을 수 없다.

2. **`layout`은 정확한 키와 타입을 가진다.**

   | 필드 | 의미 |
   |---|---|
   | `schema_version` | 정수 1 |
   | `scheme`, `sector_size` | `gpt`, 정수 512 |
   | `disk_guid`, `raw_size_bytes` | source GPT의 nonzero GUID와 sector 정렬된 image 전체 길이 |
   | `provision_role` | 기존 실험 이미지 `boot_a`, D-888 새 factory `bootstrap` |
   | `partitions` | 아래 여섯 역할의 정확한 목록 |

   각 partition의 키는 `role`, `number`, `start_lba`, `size_lba`, `type_guid`, `unique_guid`다.
   정수 자리에 bool/float/string을 받지 않는다. 알 수 없는 키·중복·겹침·범위 밖 값은 거절한다.

   | 번호 | 역할 | GPT type |
   |---:|---|---|
   | 1 | `bootstrap` | Microsoft Basic Data, FAT32 예정 |
   | 2 | `boot_a` | Microsoft Basic Data, FAT32 예정 |
   | 3 | `boot_b` | Microsoft Basic Data, FAT32 예정 |
   | 4 | `root_a` | Linux filesystem |
   | 5 | `root_b` | Linux filesystem |
   | 6 | `data` | Linux filesystem |

   이 배치는 아직 부팅 수용된 제품 형식이 아니다. GPT 구조 검증과 filesystem/부팅 검증은 구분한다.
   prototype의 boot FAT는 각각 최대 512 MiB로 제한한다. 더 큰 배치는 readback 메모리 예산과 함께 재검토한다.

3. **서명된 snapshot과 실제 source image를 결속한다.**
   Ed25519 서명 → 전체 checksum 검증의 인증된 map → manifest bytes SHA 확인 → JSON 해석 순서다.
   metadata를 다시 읽어 의미를 바꾸지 않고 검증된 snapshot을 소비자에 전달한다.
   GPT 확인 때문에 image를 추가로 읽으면 그 pass에서 소비한 compressed bytes도 인증된 SHA와 대조하고 trailing bytes를 포함한다.
   기존 v1의 image 단일 hash-read 동작은 유지한다.

4. **GPT 파싱은 제한된 크기로 수행한다.**
   protective MBR, GPT 1.0 primary/backup header, header/array CRC, 128-byte entries와 최대 128개 entry,
   mirrored arrays, GPT name/역할/번호/GUID/범위를 검증한다. 불일치는 보정하지 않고 거절한다.
   primary array는 LBA 2, backup array는 backup header 바로 앞이며 이 prototype의 entry attributes는 0이다.
   backup GPT 위치와 LBA 범위의 기준은 image raw 길이다. 큰 카드에서도 원본 table을 유지한다.
   자동 GPT relocation/repair/grow는 이 단위에 포함하지 않는다.

5. **기록 전·후의 확인 대상을 구분한다.**
   기록 전에는 signed source와 대상 serial/용량/bus/plan identity를 확인한다. 기존 카드의 MBR/GPT 배치가 다른 것은 정상이다.
   기록 후 개인화 전에 actual GPT를 source snapshot과 대조한다. 작은 카드·잘림·변경된 backup GPT를 거절한다.
   같은 크기·큰 카드의 검증 범위는 image prefix이며 이후 공간은 검증했다고 표시하지 않는다.

6. **개인화는 지정 역할의 FAT32 volume에만 쓴다.**
   partition number/GUID/offset/size와 physical disk가 모두 맞아야 한다. enumeration 순서와 drive letter를 identity로 쓰지 않는다.
   명시적 `BootMountPath`도 이 조건을 우회할 수 없다. secrets는 기록 후 layout 검증 전에 쓰지 않는다.
   readback의 기존 Windows FSInfo/status/SVI 허용은 유지하고 provisioning extras는 서명된 `provision_role`에서만 허용한다.
   다른 FAT의 kernel/config/autoboot 파일, root/data/table/gap 변경은 거절한다.
   완료한 FAT buffer는 해제하여 세 FAT를 동시에 모으지 않는다.

7. **probe/reprobe/resume도 같은 GPT identity를 사용한다.**
   GPT disk GUID와 partition snapshot을 유지한다. GPT emergency write는 이 단위에서 명시적으로 거절한다.
   기존 MBR emergency의 확인·receipt 제한은 유지한다.

### Builder implementation status (2026-10-26)

native 빌더는 기존 Ubuntu customization 결과를 읽기 전용 source로 삼아 새 GPT A/B 이미지를 조립한다. 고정 계획은29GiB raw, bootstrap64MiB, boot A/B 각각512MiB, root A/B 각각11GiB, 나머지 약6GiB data다. 일반 파일에 실제 sfdisk로 만든 GPT를 기존 bounded parser로 다시 읽는 시험을 통과했다. root별 fstab·cmdline·D-881 descriptor는 실제 PARTUUID를 사용하며 data/provision UUID만 공유한다. cloud-init의 partition grow/resize를 끄고, 공통 data에 명시적 factory schema·기존 서비스 uid/gid/mode를 초기화한다. 기체 identity·SSH private key·tailnet state는 이미지에 만들지 않는다.

조립기는 새로 할당한 loop와 backing file을 대조하고 detach 전에도 다시 확인한다. unmount/detach 실패 시 작업 공간과 image를 보존하고 발행을 거절한다. 두 root에 실제 설치된 native payload의 allocation/apparent size 중 큰 값의4배+512MiB를 추가 여유로 요구한다. 이미 복사한 pinned factory 외에 current/previous/staging과 내려받는 archive를 위한 baseline 예산이다. 용량 보고서는 artifact에 포함하며, 실제 새 ARM64 산출물의 용량 증거를 대신하지 않는다.

finalizer는 snapshot과 actual GPT를 대조한 뒤 FAT 세 개와 ext4 세 개를 검사한다. manifest producer에는 같은 snapshot을 전달한다. native ARM64 workflow는 unsigned 경계를 유지한다. 후속 OS bundle 설치는 대상 카드의 기존 GPT UUID에 root·boot metadata를 맞춰야 한다. 새 SD용 factory snapshot의 UUID를 기존 카드에 그대로 적용하면 D-881 admission에서 거절된다. 이 설치 단계는 아직 구현하지 않았다. 이 구현 상태는 privileged loop/filesystem 실행, ARM64 artifact, firmware boot 또는 OS trial/commit/fallback 수용을 뜻하지 않는다. production BUILD_GO 차단은 유지한다.

### Verification and consequences

D-888의 새 factory는 bootstrap 1을 영속 provision volume으로 쓴다. descriptor schema 2와 `ab-v2`를 함께 검증하며, 기존 boot A 실험 이미지의 schema 1/`ab-v1` 읽기 호환을 유지한다. 두 역할은 같은 GPT 물리 배치를 가지므로 parser는 서명된 기대 정책을 인자로 받고 파티션 물리 metadata 전체를 검증한다. Python readback과 PowerShell mount 선택은 이 정책을 그대로 소비한다. 기존 카드의 자동 변환은 하지 않는다.

새 카드의 깊은 진단은 signed release verifier가 돌려준 layout snapshot과 확인할 root 슬롯을 명시한다. `python deploy/robot/pinky_pro/sd/read-card-diagnostics.py --disk <확인한 디스크> --out <새 출력 폴더> --layout-file <검증한 layout.json> --slot a`를 사용한다. B 진단은 `--slot b`로 별도 폴더에 추출한다. 이 도구는 GPT 양쪽 사본과 snapshot을 대조하고 읽기 전용으로 동작하며 자체 서명 검증이나 active 슬롯 추측을 하지 않는다. 기존 MBR 진단은 두 추가 인자 없이 유지한다.

실제 signed verifier/readback/PowerShell fixture를 통한 positive/negative 회귀, legacy MBR 및 installed closure를 확인한다.
PowerShell을 실행하지 못한 skip을 통과로 계산하지 않는다. 시험 PC의 별도 pinned test-tools 환경을 사용한다.
실제 카드 기록·Pi 부팅·watchdog·전원 차단·OS trial/health/fallback·공유 데이터 schema rollback은 후속 수용이다.
source 시험만으로 해당 결과를 주장하지 않는다.

### Alternatives

첫 FAT 추측은 세 FAT 중 개인화 대상과 bootstrap을 구분하지 못한다.
unsigned layout override는 서명된 이미지와 선택 의미를 분리한다.
기존 카드 배치를 source와 기록 전에 비교하면 정상 재이미징을 거절한다.
위 대안 대신 서명된 역할과 실제 기록 후 배치를 결속한다.

### References

- [D-387](D-387-robot-updates-operator-approved-rollout.md), [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md)
- [SD personalization instructions](../../deploy/robot/pinky_pro/sd/AGENTS.md)
