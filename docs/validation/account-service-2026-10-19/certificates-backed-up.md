# Account 인증서 발급·보호 백업·갱신 타이머

2026-10-19 사용자 HTTPS 활성화/관리자 실행 뒤 후속 검증. [이전 발급 권한 거부](prepared-activation-candidate.md)는 당시 관찰로 보존한다. 이번 결과는 Account 설치·사용자 수용을 뜻하지 않는다.

## 발급과 백업

실제 준비 폴더에 TLS certificate와 root-owned0600 private key가 생성됐음을 확인했다. Tailscale의 CertDomains는1개가 됐다. OpenSSL의 시스템 CA chain verify·정확한 issuer hostname·30일 이상 잔여 유효성 검사 exit0, cryptography의 인증서/개인키 공개키 대조도 PASS했다. 만료는 **2027-01-16 17:44:47 UTC**, leaf SHA-256 fingerprint는 `B5:CB:81:96:A1:6E:F9:E9:17:9A:F2:3D:F1:D3:39:0C:AF:C1:26:B7:5A:E5:60:FE:47:D9:ED:81:69:AB:94:62`다.

사용자의 명시적 백업 지시에 따라 TLS pair·Account signing pair·준비 설정 등10개 파일과 SHA-256 manifest를 현장 root-only0700/0600 백업에 복사해 원본과 일치함을 확인했다. 기존 실행 Fleet의 로컬 image를 사용한 임시 Docker helper는 준비 디렉터리만 mount하고 network none/read-only rootfs/cap-drop ALL을 적용했다. root-owned 파일을 백업하는 데 필요한 DAC_OVERRIDE를 한정해서 사용했다. 다른 호스트 보호 설정을 읽지 않았다. 첫 helper의 quoting 오류와 DAC 권한 부족은 실행 실패로 남았으며 수정 뒤 백업/대조가 성공했다.

SSH로 받은 archive는 Windows 메모리에서 DPAPI CurrentUser로 암호화하고 현재 사용자 전용 ACL 디렉터리에 저장했다. 평문 private key는 Windows 디스크나 도구 출력에 쓰지 않았다. 복호화 후 archive SHA-256 `ac0b6839923db2d9d0f487e70e26d8db6775a5e042e9e77b54e6ff7a1943f512` 일치 PASS. 실제 현장/Windows 경로와 복원 주의사항은 canonical gitignored `private/account-service-preparation-20261019/README.md`에 있다.

DPAPI 복원에는 해당 Windows 사용자 프로필/키가 필요하다. 파일만 다른 PC/계정으로 옮겨서는 복호화할 수 없다. 현장 root 보호 백업도 별도로 유지한다. 이번 off-host 백업은 snapshot이며 미래 갱신 결과가 Windows에 자동 동기화된다는 주장은 하지 않는다.

## 갱신 운영

동일 private 폴더의 `renew-account-tls.py`와 systemd user service/timer를 현장에 설치했다. user linger=yes, timer enabled/active, 첫 oneshot Result=success를 확인했다. 첫 실제 실행 결과는 certificate_checked/pair_matches=true, changed=false였다. 기존 인증서는 충분히 유효하므로 교체하지 않았다.

매일 최대1시간 jitter·Persistent=true로 기존 Tailscale daemon에 `cert --min-validity=720h`를 요청한다. 실제 root certificate 접근은 기존 Docker 권한으로 binary/socket/준비 인증서 경로만 mount한 임시 helper에서 확인했다. 새 이미지 pull·새 상시 컨테이너·Tailscale operator 권한 변경은 없다. helper는 현재 실행 Fleet image ID를 사용하고 네트워크 namespace는 none이다. daemon이 인증서 발급 통신을 맡는다.

받은 pair는 chain/hostname/일치/30일 유효성을 검증한 뒤에만 반영하며, 변경 전 pair는 root 보호 백업에 보존한다. `/etc/rosy/account-tls`가 실제 설치된 경우 UID10001/0400으로 복사하고 기존 Caddy 설정을 reload하는 분기를 준비했다. 그 디렉터리가 없는 현재는 운영 설치·reload를 수행하지 않는다.

격리 경로에서 최초 pair 쓰기→두 번째 실행 무변경, 설치 대상 모형의 pair 일치·UID10001/0400을 실제 검사해 PASS했다. 테스트 키 복사본은 한정된 격리 경로에서 삭제했다. 운영 Caddy reload 분기·실제 만료 시 CA 재발급·reboot 후 timer 실행은 미검증이다. user unit verify는 SSH의 runtime 환경 누락으로 처음 실패했고 정확한 `/run/user/<uid>`·user bus 환경을 지정한 뒤 통과했다.

현장 Docker/Tailscale daemon과 기존 Fleet image가 계속 사용 가능해야 갱신된다. 일일 실행 결과는 user journal/service Result로 확인한다. 인증서 갱신은 Account signing key 재생성이 아니다. 운영 DB·기존 비밀번호·프로필·회수 상태는 변경하지 않았다. 아직 Authority 활성화·443 frontend 적용·signed rollout·native/사용자 로그인·실제 회수/복구 인수는 남아 있다.
