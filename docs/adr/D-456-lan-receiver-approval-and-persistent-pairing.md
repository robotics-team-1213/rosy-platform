## D-456 같은 LAN에서 장비를 선택하고 상대 화면에서 승인한다 — 오프라인과 로그인 만료는 페어링 해제가 아니다

**Status:** Accepted (2026-10-04, 사용자 결정: 상대 화면 승인 기본·QR/코드 보조·LAN 우선; 구조 결정이며 전체 구현·배포·DEVICE/FIELD 수락은 별도)

### Context

사용자는 장비와 노트북이 같은 LAN에 들어오면 주소 입력 없이 목록에서 선택해
연결하고, 처음에는 상대 화면에서 승인하며 오래 연결하지 않아도 페어링을 유지하기를
요청했다. Bluetooth는 예시였고 사용자는 다시 LAN 연결이 목적임을 명확히 했다.
다른 망은 D-452의 승인된 directory 범위를 유지한다.

현재 Fleet 등록과 Cam 자격은 SQLite에 남고 단순 발견 누락으로 삭제되지 않는다.
그러나 Native Pilot 저장 키에는 IP 목록이 포함되며 만료·검색 충돌 등 load 실패에서
암호화한 저장 기록을 지운다. Cam 자격은 180일, 현재 CORE 일반 로그인은 최대 168시간이다.
D-361의 사이트 전용 90일 토큰은 현 CORE에 구현되어 있지 않다. Fleet 카메라에는
실제 상대 승인 화면이 있지만 로봇/Pilot 공통 상대 승인 거래는 아직 없다.
장비 이름, mDNS TXT, 비인증 UID는 암호학적 신원 증명이 아니다.

### Decision

1. **같은 LAN에서는 발견 → 장비 선택 → 첫 상대 승인 → 연결이다.** 주소·개발 설정
   입력을 일반 흐름에 넣지 않는다. 앱/관제/로봇은 이미 있는 D-432·D-452 공유 발견
   cache와 서비스별 listener를 사용한다. 중복 scan·인터넷 multicast·전체 포트 scan은
   하지 않는다. 새 장비 발견은 승인이나 로스터 등록을 뜻하지 않는다.
2. **상대 화면 승인이 기본이다.** 요청 화면은 상대 이름·역할·요청 권한과 승인 대기를
   표시하고, 수신 화면은 요청 장비와 권한을 보여 승인/거절한다. 수신 서비스의 기존
   인증된 소유자가 승인한다. Fleet은 named principal 감사와 기존 권한을 유지하고,
   CORE는 기존 로컬 인증·물리 화면 소유권을 따른다. 익명 요청은 제한된 대기 거래만
   만들며 토큰·운영 로스터·제어 권한을 변경하지 않는다. 요청 queue/body/rate/시간과
   중복 승인·cancel을 제한하고, 승인 화면을 열어도 정지 접근을 막지 않는다.
3. **QR·4자 영숫자는 보조 요청 확인 수단이다.** 화면이 없거나 직접 찾기 어려울 때
   같은 승인 거래를 찾고 양쪽 장비를 대조하는 데 쓴다. 강한 요청 secret과 양측
   신원 키·nonce 결속, 수신 소유자의 명시 승인 없이 4자만으로 자격을 발급하지 않는다.
   QR에는 비밀 token을 넣지 않는다. 기존 8자 로그인·6자리 Cam 비교는 호환 경로이며
   길이만 바꾸거나 승인 확인을 생략하지 않는다. 무선 ADB·SSH는 각 플랫폼 인증을
   유지하며 앱 페어링을 OS의 관리자 접근 권한으로 승격하지 않는다.
4. **지속 승인 관계와 통신 세션을 분리한다.** 수신 소유자의 승인 record는 논리 장비
   identity, 양측 public-key fingerprint, 역할/scope, 승인 principal, revocation generation을
   보관한다. IP·last_seen·검색 TTL·일반 세션 만료는 승인 관계를 삭제하지 않는다.
   명시적인 연결 해제나 소유자 폐기만 관계를 폐기하며, 키 불일치는 관계를 보존한 채
   연결을 차단하고 별도 재승인을 요구한다. 기존 Bearer의 만료를 없애거나 자동 연장하는
   방식으로 지속 승인을 대신하지 않는다. 제어 seat·lease와 발급자 만료 제한도 유지한다.
   영구 grant 발급은 지속 소유자 권한과 provenance를 확인해야 한다. 임시 pair-admin/
   pair-physical 로그인에서 발급하면 승인 grant의 사용 수명도 발급자 만료를 넘지 못한다
   (D-193 M2). 짧은 관리자 세션이 무기한 권한을 만들어서는 안 된다.
5. **재접속은 기억한 신원을 다시 증명한다.** 현재 주소는 발견/directory에서 후보로
   얻고 승인된 키의 fresh-nonce 소유 증명과 기대한 TLS/논리 신원을 확인한 뒤 단기
   세션을 발급한다. 확인 전 새 주소로 기존 Bearer를 보내지 않는다. 오래 오프라인이었던
   동일 키 장비는 사용자에게 코드를 다시 요구하지 않는 것이 목표다. 충돌·키 변경·폐기·
   인증 실패는 다른 주소 fallback이나 자동 등록으로 숨기지 않는다.
6. **화면은 승인·접속·로그인을 별도로 표현한다.** `승인됨 / 연결 끊김`은 승인 관계를
   유지한다. 만료된 로그인에는 `승인 기록 유지 / 로그인 갱신 필요`를 보이며 현재 안전한
   갱신 경로가 없는 이미지에서는 그 한계를 표시한다. 사용자가 누르는 `연결 해제`는
   소유자 폐기이고 앱/네트워크 종료와 다르다. 재연결 자체가 주행·모드 변경·정지 해제·
   미완료 명령 재생을 시작해서는 안 된다.
7. **Bluetooth를 기본 경로에 넣지 않는다.** LAN + 승인된 외부망 directory로 진행한다.
   Bluetooth/Android CompanionDeviceManager/OS bonding은 이번 연결 전제와 구현 범위가 아니다.

### D-427·D-429·D-430 관계

| 결정 | 관계 |
|---|---|
| D-427 | `contracts/foundation`의 typed 계약, CORE 인증·장비 UI, `operations/fleet` 승인/감사, Pilot/Cam client가 기존 소유 영역과 wheel/ROS/native/Android 패키징 경계를 유지한다. 새 최상위 부분이나 복제된 인증 서버를 만들지 않는다. |
| D-429 | 페어링은 통신·접근 승인이고 로봇 제어 포트나 Device Action 실행 권한 자체가 아니다. client/provider는 기존 소유 모듈의 포트와 공용 계약을 사용하며 승인된 세션도 해당 owner의 제어 admission을 거친다. |
| D-430 | 발견·페어링·재접속은 CORE 최종 cmd_vel, StopLocal, 제어 lease, named principal, 기존 키/CA pin을 우회하지 않는다. 안전 경로 변경은 독립 리뷰를 받고 실제 구동은 별도 검증한다. |

### Alternatives and consequences

- LAN 수신 승인 기본: 주소 입력과 별도 무선 절차가 없어 선택한다. 최초 수신 확인은 필요하다.
- QR/코드 기본: 화면 없는 기기에는 유용하지만 매번 입력·촬영을 요구하므로 보조로 둔다.
- Bluetooth 기본: 브라우저·Linux/Windows·Android의 지원과 OS 권한이 달라 별도 연결 단계를
  추가한다. Android 공식 companion pairing도 자체 통신 연결을 만들지 않는다. 사용자 LAN
  요구와 맞지 않아 이번 기본 흐름에서 제외한다.

### Implementation and acceptance

현재 API에 없는 일반 수신 승인·key proof·세션 갱신은 이 ADR만으로 구현됐다고 표시하지
않는다. 다음 작업의 소유 순서는 contracts/API owner의 typed 거래와 API reference 동시 정의,
CORE 수신 승인/지속 record, Fleet 승인/감사 adapter, Pilot/Cam client와 실제 승인 화면이다.
기존 camera-only pairing을 role 값만 바꾸어 일반 장비 승인으로 재사용하지 않는다.

우선 Native Pilot의 실패 시 암묵적 저장 삭제를 제거하고, HTTPS의 검증된 hostname 기준
슬롯과 명시적 로컬 기록 삭제 경로를 적용한다. 로컬 기록 삭제는 수신 소유자의 자격
폐기나 사이트 전체 연결 해제를 뜻하지 않는다. 옛 IP 슬롯은 같은 endpoint에서 기존
trust anchor에 대한 HTTPS 서버 인증과
실제 저장 세션·robot identity 확인 후에만 이주한다. 현재 HTTP-only 이미지에는 광고 기반
Bearer 주소 추종을 적용하지 않는다. 이 단계만으로 장기 만료 뒤 무코드 갱신이 된다고
주장하지 않는다. 광고의 secure 플래그·hostname만으로 슬롯을 신뢰하지 않으며 기존
키 pin을 제공하지 않는 초기 HTTPS 단계가 영구 key continuity까지 완성했다고 주장하지 않는다.

수용은 첫 승인/거절·권한 부족·한 번만 승인·대기 제한, restart/장기 offline/DHCP 뒤 같은
키 무코드 재연결, 세션 만료 뒤 승인 보존, 키 변경/폐기/충돌에서 세션 발급과 검증 전
Bearer 전송 0, 재접속 뒤 양의 속도·모드 변경·정지 해제·명령 재생 0으로 검증한다.
SOURCE·LOCAL·CI·서명 배포·실기 두 화면 확인을 구분한다.

근거: D-193, D-341, D-361, D-432, D-452;
[Android Companion device pairing](https://developer.android.com/develop/connectivity/bluetooth/companion-device-pairing),
[ADB Wi-Fi architecture](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md).


## 2026-10-05 CORE 구현 slice와 남은 수용 경계

공유 typed 계약은 API Reference v1.101과 `core_common.protocol.peer_pairing`에 둔다.
기존 CORE overlay의 한 atomic commit을 사용하며 별도 SQLite를 도입하지 않는다.
명시적 연결 기억은 실제 현재 issuer record의 nonlegacy·nondevelopment·card/manual·
만료 없는 administrator를 `is_durable_admin`으로 확인한 경우만 persistent 관계로
허용한다. 역할 이름만으로 영구 권한을 추론하지 않는다. 임시 issuer는 최대 168시간과
issuer expiry를 함께 적용하고 관계와 단기 token의 수명을 분리한다.

원래 issuer ID/digest/source/named principal과 client/receiver P256 key, generation을
보관한다. 자식 token에 명시적 peer_binding을 저장하여 관계 누락/손상·폐기·issuer
폐기·키/권한 변경에 HTTP와 live socket 모두 fail closed한다. expired/revoked 관계는
삭제하지 않지만 status의 authorization_available을 false로 반환한다.

선택적 network.tls.ca_file은 실제 TLS provisioning 소유이며 기존 listener의
cert/key/chain/hostname 검증과 결합한다. 인증된 수신 화면의 실제 CA 지문과 D-341
anonymous first-contact/LeafBinding/물리 비교 후에만 credential 흐름을 진행한다.
4자리 번호는 요청 비교용이다. CORE 후보의 QR renderer, HTTP-only 기기 TLS 설치,
Native Pilot/Fleet/Cam 결합, native ARM crypto 실행과 signed DEVICE 수용은 별도이며
이 source slice로 전체 D-456 목표 완료를 주장하지 않는다.


## 2026-10-05 Fleet/Cam 구현 통합과 LAN 기본 흐름

사용자의 재확인에 따라 Bluetooth 없이 같은 LAN의 발견 목록에서 기기를 선택한다.
IP 입력이나 개발 설정 가져오기를 정상 접속의 전제로 두지 않는다. 최초 상대 화면 승인과
이후 신원 증명은 별도 단계이며 광고 목록만으로 자격이나 제어 권한을 주지 않는다.

API Reference v1.103의 `rosy.camera-peer/1`은 기존 Fleet 영상 자격 소유자에 둔다.
CORE 운영자 자격을 영상 자격으로 재사용하지 않는다. 현재 named site operator의
명시적 연결 기억 승인, source 점유, SQLite nonce/credential 원자적 갱신과 issuer/key/
generation 검증을 적용한다. 기억한 관계는 장기 오프라인에도 보존하지만 폐기·키 변경·
발급자 철회는 갱신을 거부한다. 최초 CA 확인은 기존 HTTPS 물리 비교 경계이며 네 문자
표시값은 요청 대조용이다. 네 문자만으로 서버 인증을 끝냈다고 주장하지 않는다.

상대 승인 화면은 공용 선택·체크·확인 컴포넌트를 사용한다. 401/403에서는 보호 목록을
지우고 같은 인증 epoch의 polling을 멈추며 명시적 재인증 뒤 다시 확인한다. 구형 수신기의
404도 자동 반복을 멈춘다. 승인이나 재연결은 카메라 촬영·lease·주행·정지 해제를 시작하지 않는다.

SOURCE/LOCAL 통합 후에도 Android 앱 빌드·기존 서명 업데이트·실제 두 화면 승인과
DHCP/오프라인 복귀·발열 대응은 각각 검증해야 한다. 이 기록은 실기 완료가 아니다.
