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

descriptor는 설치 대상·지원 상태·허용 operation을 기술한다. 실행 파일이나 shell 문장을 지정할 수 없다.
새 descriptor에 apply를 적는 것만으로 executor가 생기지 않으며, 현재 실행 대상은 Pinky뿐이다.
Pinky의 `existing_implementation`은 기존 도구 구현이 있다는 뜻으로 장치·현장 수용 완료를 뜻하지 않는다.
다른 기종을 Pinky target으로 지정해 지원 검사를 우회하지 않는다.

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
