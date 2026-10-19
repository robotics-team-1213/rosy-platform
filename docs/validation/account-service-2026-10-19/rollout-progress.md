# Account 공개 변경과 현장 전환 준비 — 2026-10-19

이 기록은 현장 로그인 활성화 완료를 뜻하지 않는다. 이전 날짜의 준비·검증 기록은
그때의 상태로 보존하며, 다음 전환 결과는 후속 기록으로 남긴다.

## 소스와 시험

- 인증 공개 후보 commit `5894130b68fe584a0da2a1a8ce065d5768611c6f`는
  원격 Linux 시험 PC에서 실제 Chromium을 포함한 17개 suite를 실행했다.
  결과는 **451 passed / 2 skipped / NEW 0**이다. 범위는 초기 비밀번호,
  프로필·관리 UI, CORE SSO·로그아웃·장애·lifespan, 공유 제어,
  site ingress·preflight·candidate·서명·updater와 tracked-secret 검사다.
- 두 skip은 시험 PC의 Docker Compose CLI 부재다. 별도 현장 CLI로 비밀 없는
  임시 env와 최종 base/Account overlay를 해석해 기존 3서비스,
  8443+443, `/etc/rosy/account-tls`의 읽기 전용 디렉터리 bind를 확인했다.
  이 별도 검사는 skip을 pytest 통과로 바꾸지 않으며 `up`을 실행하지 않았다.
- 격리한 동일 프록시 컨테이너에서 합성 CA/leaf pair를 원자적으로 교체하고
  `caddy reload --force` 뒤 새 인증서를 제공하는 것을 확인했다.
  실제 서비스 개인키를 시험 데이터로 사용하지 않았다.
- 공개 pre-push는 변경 전 main에서도 재현된 충전 lifespan SIM 실패로 중단됐다.
  별도 후보 commit `eea981799fbac009c63c98f69bafd7f14f103882`는 실제 세 worker를
  라운드마다 완료·대기시켜 다음 센서 프레임이 진행 중인 ACK 읽기를 앞지르지
  않게 한다. 독립 검토 지적 사항은 해소됐고 빠른 계약 검사 519개는 통과했다.
  같은 후보의 3회 반복 lifespan 단독 검사는 exit0으로 통과했다. 전체 변형·
  affected·CI는 이 기록 시점에 진행 중이다. 실패 목록·안전 기준·
  생산 timeout은 바꾸지 않았다.

시험 로그는 저장소 밖 `rosy-account-rollout-20261019/public-release-5894`,
`station-clock-rounds`와 `remote-pytest/eea981799fba`에 보관한다.
각 SHA의 원격 시험·독립 리뷰와 공개 main의 CI·배포 증거를 섞지 않는다.

## 현장 상태

- Fleet·Vision·프록시는 기존 commit `e5661d443f41fcc665115c59af240fe4755bc3d0`으로
  동작하며 8443만 게시한다. Account 설정은 아직 비활성이다.
- 기존 signing key를 재사용해 Authority 설정·키·TLS pair를 보호 경로에
  UID10001, 디렉터리0700/파일0400으로 준비했다. 실제 parser와 TLS pair 검사는
  통과했지만 listener·사용자 원장을 전환하지 않았다.
- DB/설정의 일관 백업, 현장 root 보호 인증서 백업과 별도 Windows DPAPI
  암호화 백업을 보관한다. DPAPI 복원에는 원래 Windows 사용자 프로필의 키가
  필요하다. 갱신 timer는 enabled/active이고 원자적 교체 뒤 강제 reload를 사용한다.
- 준비용 자동 업데이트 보류는 **2026-10-19 04:37:33 UTC**에 해제했다.
  실제 전환 때 최신 백업과 기존 보류 소유자를 다시 확인한다.
- 확인된 사람 계정은 5개, 기계 항목은 4개다. 호환 receiver 배포 후 첫 Authority
  bootstrap 전에 사람만 요청된 `아이디!` 초기값으로 전환하고 최초 변경을 요구한다.
  기계 자격은 유지한다. 확인하지 못한 추가 사람 계정은 추측해 생성하지 않는다.

## 남은 인수

정확한 공개 main의 CI와 서명 candidate를 확인한 뒤 verifier/updater 호환 설치,
양쪽 ingress 검사, 사용자 이관과 실제 로그인·프로필 변경·회수를 검증한다.
확인된 native client 외 앱의 정확한 callback/resource와 Android production signer,
실제 단말 앱 링크 및 사용자 수용은 미완료다. 로봇 동작 수용을 호스트 시험으로
대신하지 않는다.
