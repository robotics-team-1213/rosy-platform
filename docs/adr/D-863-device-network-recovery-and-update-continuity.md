# D-863 — 장치 네트워크 복구와 서명 업데이트 연속성

**Status:** Accepted for implementation (2026-10-24, 사용자 전체 범위 승인).
SOURCE 시험·실제 장치·배포 수용은 별도로 기록한다.

## 문제

SSID 변경 화면과 CORE API가 있어도 native Host Agent의 lane-only allowlist에는
`network.connect`가 없다. 일반 subprocess 구현도 기존 프로필을 먼저 덮어쓴다.
첫 부팅 재시도는 원래 번들의 Wi-Fi를 다시 기록하므로 별도 인계 없이 복구 UI만
추가하면 변경이 되돌아간다. 현재 이미지 계층 sync는 first-boot를 전달하지 않아
새 카드와 OTA 장치가 서로 다른 복구 코드를 실행할 수 있다.

## 결정

- 기존 차선 Host Agent와 최종 Base/OMX 명령 소유권은 유지한다. 별도 network-only
  native agent를 두며 CORE와 recovery 전용 Unix socket을 각각 전용 peer UID로 제한한다.
- 네트워크 agent의 허용 명령은 `network.status`, `network.connect`, `network.start`다.
  connect는 작업 ID와 비밀 없는 준비 기록만 응답하고 PSK는 메모리에만 보유한다.
  HTTP 응답 flush 이후 start가 해당 준비 작업을 실행한다. 재시작으로 PSK를 잃으면
  자동 실행하지 않고 명시적인 재입력을 요구한다. 모터·서비스 변경·셸·재부팅·릴리스
  명령을 이 agent에 추가하지 않는다.
- 기존 CORE 관리자 인증·재확인·idempotency를 유지한다. 운영 네트워크 라우트만 새
  socket으로 연결한다. 초기 부팅 복구 HTTPS는 별도 한시적 network-only 세션이며
  CORE administrator 토큰이나 일반 로봇 명령을 발급하지 않는다.
- SSID는 인쇄 가능한 UTF-8 1–32바이트, PSK는 지원 WPA2 passphrase로 검증한다.
  후보 UUID와 실제 SSID·인터페이스의 IPv4·NM 활성 상태를 확인한 후 확정한다.
  기본 경로나 인터넷이 없는 정상 현장 LAN도 인정하고 해당 관측은 별도로 표시한다.
- 기존 SITE_PROFILE은 후보 확인 전 수정/삭제하지 않는다. 오류·중단·확정 실패는
  이전 프로필로 복구하고, 복구가 검증되지 않으면 held로 남긴다. 상태·감사·예외·argv에
  PSK를 넣지 않는다. NM keyfile·변경 저널은 root-only/no-follow로 관리한다.
- 기존 전역 rosy_claim 획득 → change.lock 획득 → 안전 조건 재검사 순서로
  업데이트·무선 변경을 배제한다. first-boot retry와 fallback AP 조작도 같은 잠금을
  소비한다. 이동/권한/정지 상태가 불명확하면 needs_maintenance로 거절하고 네트워크
  기능이 임의로 모터/서비스를 정지하거나 운용 모드를 승격하지 않는다.
- 복구 결과를 device UID·hardware serial·원본 번들 checksum·NM UUID에 묶어 첫 부팅에
  넘긴다. 실제 연결을 검증한 경우만 원본 번들 Wi-Fi 덮어쓰기를 건너뛰며 complete.json은
  실제 SSID를 기록한다. 다른 보드의 카드 재등록/SETUP 승인을 우회하지 않는다.
- 초기 실패용 HTTPS는 유효한 장치 신원·hardware 일치·AP에서 활성화하며 handoff 미지원은
  읽기 전용 진단만 제공하고 쓰기를 image_required로 거절한다. 서비스는
  AP 주소의 8443에만 바인딩한다. root issuer와 비권한 HTTP를 분리한다. 8문자 일회용
  recovery code, scrypt 검증, 10분 만료, 5회 실패 제한, 부팅/AP 결속, 재시작에도 유지되는
  소비 기록을 사용한다. Secure/HttpOnly/SameSite Strict와 CSRF·동일 Origin/Host·4KiB
  제한을 적용한다. 최초 인증서 지문은 LCD/콘솔과 물리적으로 대조하고 로컬 신뢰를
  등록하며 HTTP/인증서 무시로 강등하지 않는다.
- signed native payload의 허용 boot catalog와 기존 updater를 사용한다. fresh-image와
  OTA 파일 집합을 검증하고 장치 설정·신원·지도·보정 자료를 release가 덮어쓰지 않는다.
  신규 boot mutation은 bridge capability 이후에만 허용하며 구형 release의 sync 전에
  새 조정자가 검증된 inverse를 완료한다. 정전/역변환 실패는 held이고 성공으로 간주하지 않는다.
- 기존 timer·서명·canary/wave·hold·idle·배터리·claim·health·rollback은 유지한다.
  bridge는 기존 `payload-<id>`, boot catalog 기능 릴리스는 `payload-v2-<id>`로 발행한다.
  구형 선택기는 bridge만 보고 준비된 선택기는 두 세대의 서명 rollout을 검증한다.
  v2 discovery cache는 구형 cache와 분리하며 같은 ID의 중복 세대 발행은 거절한다.
  지원 migration 없는 OS/커널/파티션/runtime 변경은 image_required로 보류한다.
  소스 수정만으로 배포되지 않으며, 실물 SD의 자동 파괴적 재이미징은 하지 않는다.

## 검증

실제 설치 entrypoint·소켓/UID/명령 거부, 후보→확정/실패→복구, 무선/업데이트 경쟁,
first-boot 인계, secret 비노출, 인증·응답 후 시작·재접속, signed catalog·구형 rollback·
정전 reconcile을 원격 회귀에서 확인한다. 일반 HostAgent mock이나 UI 존재는 배포
동작의 근거가 아니다. signed ARM64 이미지 및 실제 Pinky radio/복구/OTA 수용은 별도다.

관련: D-26, D-161, D-176, D-192, D-388, D-412, D-418.

| 기존 구조 결정 | 관계 |
|---|---|
| D-427 | 기존 deploy/native 및 CORE/UI 소유 경로에서 구현한다. |
| D-429 | 장치 호스트 권한은 network-only agent에 남긴다. |
| D-430 | Base/OMX 최종 명령 경로를 추가하지 않으며 정지 증거와 claim을 요구한다. |
