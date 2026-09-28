# GitHub 기반 ROSY 런타임 업데이트

현재 범위는 로컬 구현과 시험이다. Pi 실기기는 컨셉 단계이며 공개 GitHub 저장소,
실제 릴리스 키, ARM64 배포 산출물은 아직 준비하지 않았다. 아래 명령은 향후 운영 절차다.

## 동작과 경계

`GitHub Release → 다운로드 → 사전 등록 공개키로 서명 검증 → staging → 운영자 설치 → 건강 확인`

타이머는 확인·다운로드·검증까지만 한다. 설치 전에 ROSY 컨테이너를 모두 정지해야 한다.
성공, 실패 후 복구, 재부팅 모두 `core` 모드로 시작한다. 모터 운용 재개는 별도 현장 검증이다.
Linux 커널, 부트로더, rootfs, Docker 및 이 호스트 업데이트 도구 자체의 자동 교체는 포함하지 않는다.
Host Agent 소켓/대시보드에서 이 CLI를 호출하는 경로도 이번 구현에 포함하지 않는다.

## 릴리스 제작과 공개 준비

1. 선택한 커밋에서 ARM64 `deploy/robot/pinky_pro/Dockerfile`의 `core`, `io` 대상을 빌드하고 별도 검증한다.
2. 비밀값 없는 `runtime/compose.yaml`과 해당 compose가 참조하는 `runtime/config/`를 준비한다.
   두 이미지의 `docker image save` 결과를 `images/rosy-core.oci.tar`, `images/rosy-io.oci.tar`에 둔다.
   파일명은 기존 계약을 따르지만 로더 입력은 Docker save/load 형식이다.
3. `deploy/robot/pinky_pro/release/manifest.schema.json`에 따라 `manifest.json`을 작성한다.
   `containers` 값은 로컬 Docker 이미지의 `docker image inspect --format '{{.Id}}'` 결과다.
   레지스트리의 멀티플랫폼 manifest digest와 혼용하지 않는다. 실제 ARM64/Linux인지 로더도 검사한다.
   `files`는 manifest와 서명 메타데이터를 제외한 모든 payload 경로와 SHA-256이다.
   `git_revision`은 전체 커밋 SHA, `minimum_bootloader`는 현재 지원 범위에서 `null`이다.
4. 기존 [키 관리 절차](release-signing-key.md)에 따라 외부 서명 환경에서 번들을 만든다.
   개인키는 payload 밖에 유지한다. 공개키 파일명은 `<signing_key_id>.pem`이다.

```bash
python3 deploy/robot/pinky_pro/release/package_release.py payload rosy-release-2026.09.08-001.tar.zst \
  --public-key /secure/rosy-release-1.pem --private-key /secure/rosy-release-1.key
```

저장소 공개를 결정한 뒤에만 `OWNER/rosy`를 실제 소유자로 바꾸고, 공개키만
`deploy/robot/pinky_pro/release/public-keys/`에 커밋한다. GitHub의 `ROSY_RELEASE_KEY_ID` 변수와
`release` 환경을 설정한다. 승인된 커밋을 가리키는 `YYYY.MM.DD-NNN` 태그의 draft release에
외부에서 만든 서명 번들을 업로드한 다음 `publish-release.yml`을 수동 실행한다.
워크플로는 서명·태그·커밋 일치를 확인한 뒤 공개한다. ARM64 빌드나 실기기 검증을 대신하지 않는다.
공개 저장소 전환 전에는 전체 이력의 비밀값·라이선스·배포 권한 검토가 별도로 필요하다.

## 향후 호스트 등록

기존 Pi 설치 절차로 Python 3, PyYAML, OpenSSL, zstd, Docker Compose와 전용 비root 계정을 준비한다.
`/etc/rosy/runtime.env`에는 기존 설치에서 생성한 `ROS_DOMAIN_ID`, `ROSY_NAMESPACE`,
`ROSY_UID`, `ROSY_GID`를 사용한다. 로봇 번호를 임의 기본값으로 대체하지 않는다.
기존 설정 `/etc/rosy/rosy.yaml`과 데이터 `/var/lib/rosy`를 먼저 확인한다.

```bash
sudo bash deploy/robot/pinky_pro/install-update-tools.sh
sudo install -m 0644 /trusted/rosy-release-1.pem /etc/rosy/trusted-release-keys/rosy-release-1.pem
```

root가 소유하는 `/etc/rosy/updates.json`을 작성한다. `os_suite`는 실제 호스트와 일치해야 한다.

```json
{"repository":"OWNER/rosy","signing_key_id":"rosy-release-1","os_suite":"trixie"}
```

저장소를 아직 사용하지 않는 환경에서도 동일한 키 등록 후 오프라인 번들을 stage할 수 있다.

```bash
sudo rosy-release stage /trusted/rosy-release-2026.09.08-001.tar.zst --json
# 또는 공개 저장소 연결 후:
sudo rosy-release check --download --json
sudo rosy-release status --json
```

## 유지보수 설치와 복구

실기기에서는 먼저 현장 정지·안전 상태를 확인한다. 서비스 정지 후 남은 ROSY 컨테이너도 정지한다.

```bash
sudo systemctl stop rosy-runtime.service
sudo rosy-release runtime down
sudo rosy-release install --release-id 2026.09.08-001 --json
sudo rosy-release status --json
```

첫 설치 성공 후에만 아래 명령으로 부팅 서비스를 활성화 레코드 기반 실행으로 전환한다.
이후 자동 확인을 원할 때 타이머를 별도로 활성화한다.

```bash
sudo bash deploy/robot/pinky_pro/install-update-tools.sh --activate-boot
sudo systemctl enable --now rosy-update-check.timer
```

명시적 이전 버전 복구는 서비스/컨테이너 정지 후 `sudo rosy-release rollback --json`이다.
중단된 트랜잭션은 `sudo rosy-release recover --json`으로 먼저 복구한다.
`RECOVERY_HELD`는 원인을 점검한 뒤 정지 상태에서 `clear-hold`를 명시적으로 사용한다.
확인이 끝나지 않은 저널이 있으면 `runtime up`은 거부한다.

`activation.json`이 선택한 세대마다 읽기 전용 설정·데이터 스냅샷과 쓰기 가능한
`/var/lib/rosy/data-working/<generation>`을 만든다. 최초 이관에는 실제 HOME 데이터인 `.rosy`도 포함한다.
롤백은 이전 세대의 작업 데이터를 다시 사용하므로 신규 버전에서 추가한 데이터가 자동 병합되지는 않는다.
이전 활성화 포인터는 CORE 쓰기 영역 밖 `/etc/rosy/previous-activation.json`에 저널과 함께 기록한다.
작업 세대와 이미지의 자동 정리는 이번 CLI에 연결하지 않았다. 용량 부족 시 업데이트를 거부하며,
정리는 [보관 정책](release-retention.md)에 따라 현재·이전 활성화와 사용자 데이터를 보존해 수행한다.

로컬 시험은 서명·변조·경로 탈출·용량·경쟁·실패 복구를 검증한다. 실제 ARM64 이미지 로딩,
컨테이너 건강 확인, Pi 전원 차단 후 복구, 하드웨어 운용은 실기기 수용 시험까지 **HOLD**다.
