# 다기종 배포 도구

저장소 루트에서 `python tools/release/deploy_cli.py list`로 배포 대상과 차단 이유를 확인한다.
기체에 연결하기 전에는 `plan`을 사용한다. 계획 출력은 서명 검증·설치 허가·장치 수용 증거가 아니다.

## 책임과 파일 위치

| 책임 | 정본 | 실행·설치 관계 |
| --- | --- | --- |
| 공통 release 서명·checksum | `deploy/hosts/common/release/signing.py` | 기존 Pinky signing import는 같은 모듈을 참조. native 설치본에는 정본을 독립 `signing.py`로 복사 |
| 대상 선택·명령 조립 | `tools/release/deployment_targets.py` | target descriptor를 검증하고 검토된 executor만 선택 |
| 운영 CLI | `tools/release/deploy_cli.py` | list/plan/apply/rollback. 임의 shell 명령을 받지 않음 |
| Pinky 제품 정책 | `deploy/robot/pinky_pro/` | 이미지·native units·SD·manifest/updater·기존 push/rollback executor 유지 |
| RaspTank 배포 상태 | `deploy/robot/rasptank_metal/deployment-target.json` | source-only, 실행 operation 없음. 실제 profile 소스는 `middleware/devices/rasptank/profile` |
| 외부 SDK 호스트 상태 | `deploy/hosts/sdk/dji_neo_2/deployment-target.json` | 공식 SDK 미지원, 실행 operation 없음. 기체 firmware 배포 대상 아님 |
| OMX 호스트 상태 | `deploy/robot/omx/deployment-target.json` | 기존 workcell 구현은 있지만 공통 이미지·업데이트 executor는 없음 |

descriptor는 설치 대상·지원 상태·허용 operation을 기술한다. 실행 파일이나 shell 문장을 지정할 수 없다.
새 descriptor에 apply를 적는 것만으로 executor가 생기지 않으며, 현재 실행 대상은 Pinky뿐이다.
Pinky의 `existing_implementation`은 기존 도구 구현이 있다는 뜻으로 장치·현장 수용 완료를 뜻하지 않는다.
다른 기종을 Pinky target으로 지정해 지원 검사를 우회하지 않는다.

list와 plan의 `delivery`는 platform·architecture·image_backend·application_updater·os_updater·os_compatible·os_tag_prefix를 표시한다.
현재 Pinky의 검토된 결속은 Pi5/arm64, native-release, RAUC, `rosy-pinky-pro-ab-v2`, `os-pinky-pro-`다.
RaspTank·DJI·OMX의 실행 backend는 null이며 descriptor 수정만으로 활성화할 수 없다.
이미지 준비 진입점은 작업 폴더·다운로드·VM 생성 전에 `require_image_backend()`로 지원 여부를 확인해야 한다.

## 명령

다음은 검토용 예시다. 실제 주소·키·산출물은 개인 입력으로 공급한다.

```powershell
python tools/release/deploy_cli.py list

python tools/release/deploy_cli.py plan --target pinky_pro --operation apply `
  --robot robot.example --tarball C:/releases/signed-release.tar.gz `
  --public-key C:/keys/release-public.pem

python tools/release/deploy_cli.py plan --target rasptank_metal --operation apply --robot robot.example
python tools/release/deploy_cli.py plan --target dji_neo_2 --operation apply --robot sdk-host.example
```

차단된 target의 plan은 `blocked: true`, 빈 command와 이유를 출력하고 실행하지 않는다.
apply/rollback으로 요청하면 거절한다.

검증된 Pinky 기체와 승인된 signed release를 실제 배포할 때는 다음 진입점을 사용할 수 있다.

```powershell
python tools/release/deploy_cli.py apply --target pinky_pro --robot robot.example `
  --tarball C:/releases/signed-release.tar.gz --public-key C:/keys/release-public.pem

python tools/release/deploy_cli.py rollback --target pinky_pro --robot robot.example
```

이 두 명령은 네트워크 접속·설치/복구를 수행한다. CLI 소스 준비 자체가 실제 기체 배포 승인은 아니다.
실행은 기존 `rosy-release-push.ps1`에 위임하며 서명·checksum·SSH host-key·장치 측 검증·실패 복구를 유지한다.
운영 PC에 PowerShell(`pwsh` 또는 Windows PowerShell)과 기존 Pinky 도구의 의존성이 필요하다.
기존 script를 직접 사용하는 방식도 유지한다. 추가 SSH 계정/known_hosts 등 기존 고급 옵션이 필요하면
해당 script의 명시적 옵션을 사용한다. 새 CLI에 임의 인자 전달이나 Force 우회는 없다.

stdout은 JSON이며 실제 executor 진단은 stderr로 전달된다.
성공은 0, argparse 입력 오류는 2, 지원/검증 거절은 3이며 executor 실패는 nonzero로 전파한다.
JSON의 `executed`는 executor 호출 여부이며 설치나 물리 동작 성공을 증명하지 않는다.

## 제품 기종 설정 검증과 마이그레이션

`ROSY_DEPLOYMENT=device`인 CORE는 선택 모델의 **설치된 ament share**가 있어야 시작한다.
소스 checkout의 profile 존재는 설치를 대신하지 않는다. 프로파일과 capability YAML은
설치 package의 정적 기본 설정과 타입을 포함해 일치해야 하며, 검증한 snapshot을 그대로 소비한다.
다른 기종 파일·미설치 모델·잘못된 YAML은 서비스 조립 전에 거절한다.

각 모델 package의 `config/deployment-binding.yaml`은 내부 배포 계약이다.
정수 schema_version 1, package model ID, `profile.yaml`/`capabilities.yaml`의 승인된 digest를 포함한다.
digest는 파싱한 YAML 값을 `json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)`로
정규화한 UTF-8 바이트의 SHA256이다. CORE가 실제 소비할 canonical snapshot과 검증하므로
설치된 RaspTank 패키지 안에 Pinky 설정 전체 또는 capability만 잘못 복사한 경우도 거절한다.
이는 승인 파일의 일관성 검사이며 물리 센서·보정·기능 수용 증거가 아니다.

binding은 source 검토·서명 릴리스에 포함하는 release-owned 정보다. 시작/설치 때 현 파일로
자동 재생성해서 오류를 덮지 않는다. CORE와 모델 profile package를 같은 호환 릴리스로 갱신해야 하며,
binding이 없는 예전 package는 제품 시작에서 거절한다. `install(DIRECTORY config ...)`가 이 파일도 설치한다.

개발 모드의 절대경로 overlay와 기존 Compose core/motor/hardware variants는 유지한다.
`Pinky Pro Pi5 Lite` 개발 profile이나 제한된 개발 capability를 native 제품 overlay로 복사하는 것은
허용하지 않는다. 기존 native 운영자가 정적 profile/capability를 수동 수정했다면 다음을 검토한다.

1. 기존 설정과 보정값을 비공개 위치에 보존하고 현재 선택 모델·설치 release를 확인한다.
2. 정적 profile/capability override를 제거하거나 해당 설치 package의 원본으로 복구한다.
3. 속도 제한·센서 보정·commissioning은 각 기존 runtime 설정과 수용 절차에서 관리한다.
   정적 기본값 복구만으로 모터·센서·항법 기능을 활성화하지 않는다.
4. package의 기본 물리 구성이 실제 장치와 다르면 기종별 승인 variant/package를 먼저 준비한다.
   내용 비교를 느슨하게 하거나 device marker를 제거해 기동하지 않는다.

native 기본 생산자는 `rosy-core.service`와 first-boot의 CORE HOME overlay다.
새 profile/capability variant는 실제 설치 package와 배포 생산자·수용 근거를 함께 변경해야 한다.

## 검증 범위

기종 결속 시험, legacy/common signing module identity, 저장소 없는 native 설치본 실행,
서명 rejection coverage, 실제 dispatcher의 인자/오류 전파와 미지원 target 무호출을 원격 시험한다.
이 시험은 ARM64 이미지 빌드·SD readback·기체 부팅·SDK 연결·모터/팔/비행 수용을 대신하지 않는다.

기종 접수와 공식 SDK 근거는 [다기종 배포 준비](multi-device-onboarding.md),
RaspTank 부품·SD 입력은 [Pi 4 준비서](rasptank-pi4-preparation.md)를 따른다.

새 이미지의 전 계층 자동 갱신 요구는 [자동 OS 업데이트 완료 기준](../plans/2026-10-25-rosy-layered-automatic-updates-design.md)을 따른다.
현재 target CLI와 payload updater 소스 존재만으로 OS 전체 자동 업데이트가 완료되지는 않는다.

## Windows의 OS 서명 준비 도구

Windows x86_64 운영자 PC에서 다음 명령으로 공개 도구 입력을 준비한다.

```powershell
python tools/release/prepare_os_tools.py
```

기본 cache는 현재 사용자의 LOCALAPPDATA 아래 Rosy/os-tools다. 새 cache만 owner-only ACL을 만들고,
기존 cache·파일은 권한·크기·checksum을 검증한다. 잘못된 기존 입력은 덮거나 권한을 바꾸지 않는다.
공개7-Zip MSI를 읽기 전용 database/CAB로 열어 고정한 구성 요소만 추출하고, QEMU 패키지와 Ubuntu 도구 guest 입력을 검증한다.
설치 프로그램 실행·호스트 기능 변경·기체 접속은 없다. WindowsGuest는 검증한 패키지를 새 작업 공간에 추출하고
소유 콘솔의 SSH host key와 정확한 커밋을 결속한다. 이 VM은 Linux 준비·검증용이며 native ARM64 이미지 빌더가 아니다.

추적된 inputs.lock.yaml의 CMS 공개 인증서 지문은 engineering 이미지 준비용으로 선택했다.
선택 근거와 정확한 PEM/SPKI는 public-keys/README.md에 있다. production ownership/rotation과 실물 수용은 별도로 유지한다.
큰 bundle 반환은 console-pinned SCP/SFTP와 hash/size 검증을 사용하며, 기존 출력에 덮지 않는 게시에는 hard-link 지원 파일시스템이 필요하다.

OS bundle 외부 서명은 세 부분으로 나뉜다. guest의 `os_bundle_external.py prepare`가 인증된 dist에서
공개 요청과 임시 서명 bundle만 내보낸다. Windows의 `external_os_signing.sign_inline_cms()`는 정확한 inline manifest,
이미지 해시·소스·factory·공개 certificate/SPKI pin을 대조하고 운영자 PC의 키로 CMS를 만든다.
guest의 `os_bundle_external.py finalize`는 그 CMS를 교체하고 기존 RAUC 검증기로 확인한 bundle과 unsigned metadata를 반환한다.
private key는 guest·CI·공유 시험 PC에 복사하지 않는다. 실제 device의 verifier는 최종 Ed25519 metadata도 요구한다.

서명·검증된 A/B image dist가 준비되면 다음 운영자 명령으로 OS 업데이트5개 산출물을 만든다.
키 경로는 운영자 보호 폴더의 기존 키를 지정한다. private key를 dist·소스·tools cache에 넣지 않는다.

```powershell
python tools/release/prepare_os_release.py --target pinky_pro `
  --dist C:/releases/verified-signed-image --output C:/releases/signed-os-update `
  --private-key C:/operator-keys/release-private.pem `
  --public-key deploy/robot/pinky_pro/release/public-keys/rosy-release-2026-01.pem `
  --cms-private-key C:/operator-keys/os-cms-private.pem `
  --release-id YYYY.MM.DD-NNN --source-revision EXACT_IMAGE_SOURCE_COMMIT --canary pinky-first
```

명령은 target 지원 여부와 인증된 image/factory metadata snapshot을 확인하고, 공개 입력만 owned VM에 넘긴다.
파일은 서버가 응답을 시작하기 전에 size/hash를 검증한 임시 snapshot으로 고정한다.
VM 요청과 최종 metadata를 운영자의 source/release/factory/certificate pin에 대조한 뒤 로컬 CMS·Ed25519 서명을 만든다.
최종 서명 metadata/rollout을 기존 device consumer로 다시 검증하고 VM과 HTTP를 닫은 후에만 새 output을 노출한다.
기존 output에는 덮지 않는다. 실패한 보호 workspace는 조사·복구를 위해 tools cache에 남고 공개 staging은 제거한다.
이 명령은 이미 인증된 signed image를 입력으로 받는다. CI run/source 결속, native image build·image 서명·최종 이미지 선택과
실제 게시의 성공 근거는 별도로 확인해야 한다. 모델 VM 연결 시험을 실제 A/B 이미지 수용으로 기록하지 않는다.
게시 도구 `publish_os_release.py`는 기본 dry-run이며 apply도 검증된5개 산출물을 engineering prerelease로만 게시한다.
GitHub의 개별 파일 제한에 맞춰 2 GiB 이상인 bundle은 복사·원격 초안 생성 전에 거절한다. 큰 bundle의 분할 전송을 제공하는 것은 아니다.
실제 배포 결과는 해당 artifact·서명·게시 영수증과 별도로 확인한다.

A/B v2 장치의 로컬 OS 상태와 공통 업데이트 정책은 다음 명령으로 읽는다.

```bash
sudo python3 -I -B /opt/rosy/os-bootstrap/native-runtime/os_update_controller.py status
```

응답의 `state`에는 검증된 현재 실행 슬롯, 기록된 committed 슬롯·릴리스, pending 단계·후보·출발/대상 슬롯,
실패 버전 이력과 `policy.enabled`·`repo`·`hold` 종류가 담긴다. `committed`는 트랜잭션 기록이며,
카탈로그 최신 버전이나 설치 패키지 전체의 readback을 뜻하지 않는다. 이 명령은 업데이트 적격성을 승인하지 않고
네트워크 확인·설치·hold 만료 처리·재부팅을 수행하지 않는다. 설치 파일 인자는 거절한다.
정책·상태가 읽히지 않으면 정상 idle로 초기화하지 않으며, 비공개 URL·hold 자유 메모·boot/transaction 식별자는 출력하지 않는다.

ARM SYSTEM guest의 양방향 비활성 설치·복구 관측은 [검증 기록](../validation/pinky-os-arm-system-2026-10-28/result.md)에 있다.
복구가 SSH 준비보다 먼저 끝날 수 있어, 시험은 원래 cloud observer에서 target journal을 읽기 전용으로 확인한다.
이는 합성 DT·정책·application을 사용한 kernel 경계 검증이며, 제품 이미지·Pi firmware·실물 수용을 대신하지 않는다.
