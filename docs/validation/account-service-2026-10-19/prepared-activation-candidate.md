# Account 활성화 후보 준비와 설정 포함 Cam 빌드

2026-10-19 사용자 추가 지시로 대기 보고에서 실제 준비 작업으로 진행했다. [앞선 선행 조건](activation-prerequisite-readback.md)은 당시 기록으로 보존한다. 이번 작업도 운영 활성화 증거가 아니다.

## 준비한 실제 산출물

현장 SSH 사용자의 홈 아래 owner-only 준비 디렉터리(0700)에 Ed25519 signing/private·public PEM, Authority 후보 JSON, Cam 공개 설정 JSON, 현재 실행 Caddyfile 기반의 추가443 frontend 후보, Compose 변경 후보, 상태 파일을 생성했다. 설정·키는 0600이며 private PEM 원문은 출력하거나 APK/공개 문서에 넣지 않았다. 이미 키가 존재하면 재사용하는 방식이다. 키를 다시 만들거나 운영 계정을 승격하지 않았다.

기존 사이트의 실제 tailnet DNS를 issuer 후보로 사용했다. 새 Account site namespace와 확인된 기존 bootstrap 로그인은 private 후보에 명시했다. 정확한 Cam HTTPS callback·client·site resource를 등록했다. 아직 승인·설치된 운영 식별자로 간주하지 않는다. 현재 로봇 roster가 비어 있어 Pilot/CORE의 자원·호스트·CA를 추측하지 않았다. Learning/Games도 실제 설치 origin/resource 확인이 남아 있다.

준비한 Authority 설정은 실행 Fleet 컨테이너의 **기존 `load_account_config`를 UID10001로 실행해 PASS**했다. 검증에는 owner-only 임시 파일을 사용했고 자동 삭제했다. 이는 parser/키 형식 검사이며 실제 issuer 연결·원장 bootstrap·사용자 로그인 검사가 아니다.

HTTPS 후보는 기존8443 및 backend의 site CA 검증을 유지하고, 별도 인증서를 쓰는 issuer443 frontend를 추가한다. Compose 후보의 신규443 publish는 기존 tailnet IPv4에 한정했다. 현재 실행 proxy의 `caddy adapt`로 후보 문법이 PASS했다. 새 인증서가 없으므로 Caddy TLS validate와 실제 protected env를 사용한 전체 Compose merge 검증은 미실행이다. 서비스를 재적용하지 않았다.

구체적 파일·관리자 명령은 canonical gitignored `private/account-service-preparation-20261019/README.md`에 있다. 공개 설정/후보 파일도 같은 private 폴더에 보관했고 현장 준비 폴더에 안내를 전달했다. private signing key는 현장 보호 폴더에만 있다. 백업·정확한 등록 확인·기존 서명 candidate 통합·권한·readback·실사용 수용 순서를 준비했다. 후보 overlay의 즉시 운영 `up`은 실행하지 않았다.

## 실제 인증서 발급 시도

후보 issuer에 대해 `tailscale cert --cert-file=<protected-stage>/account-frontend.crt --key-file=<protected-stage>/account-frontend.key <site-MagicDNS-name>`을 실제 실행했다. 결과는 exit 1, `Access denied: cert access denied`였으며 인증서는 생성되지 않았다. CLI는 sudo 또는 사전에 승인된 operator 설정이 필요하다고 안내했다. 이것은 OS/daemon 권한 거부이며 자동 승인 심사 결과가 아니다. sudo 비밀번호를 채팅으로 요구하거나 Docker로 호스트 보호 파일을 우회하지 않았다.

현장 관리자에게 필요한 정확한 `sudo tailscale cert` 명령을 private 안내에 넣었다. tailnet HTTPS 정책 동의가 추가로 필요할 수 있으며 그 여부는 미확인이다. Funnel·public ingress를 활성화하지 않았다. 근거: [Tailscale HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates), [Linux operator 권한](https://tailscale.com/docs/reference/troubleshooting/linux/linux-operator-permission).

## Cam 설정 포함 빌드

private key가 없는 Cam 공개 설정만 승인된 모델 PC로 전달했다. 제품 소스 `30acdffbfb`의 immutable git archive에서 기존 SDK·wrapper를 사용했다. task는 `assembleDebug -Prosy.accountConfig=<candidate-json> --max-workers=1 --no-daemon`이며 MemoryMax=6G·CPUQuota=200%·nice15·timeout600초를 적용했다. 새 SDK/의존성은 추가하지 않았다.

실제 결과: **configured Cam debug APK PASS**, APK의 `assets/account-config.json`과 후보 JSON의 구조화된 전체 값이 일치했다. APK SHA-256 `a0afae1a3c79d0b416de5132d8f69e163c96abd1dc0477d62ba8985bb7404b05`, build.log SHA-256 `f06fb51206aeda38e53a6dc3bc8c4dbda1fa9a78f2cb313758eee5b33fa9c14d`. 원격 외부 증거 폴더 이름은 `rosy-cam-account-configured-iHO7ps`다. 이 실행은 설정 asset 생성/패키징을 확인한 것이며 이전 전체 JVM 결과를 재실행했다고 주장하지 않는다.

운영 signer·assetlinks·기기 설치·Keystore·실제 OAuth callback·issuer 신뢰는 미검증이다. Pilot 설정 포함 빌드는 정확한 robot 등록 뒤 수행한다. Authority 설치/활성화·기존 DB 마이그레이션·서비스 재시작·운영 DB 백업/복원·main 착지/CI/서명 배포도 미수행이다.
