## D-939 앱 연동 코드는 한 곳에 둔다 — 앱 사이 사본 금지

**Status:** Accepted (2026-10-31, 사용자 결정 "연동을 더 원활하게 하고 이런 규칙도 아예 세워서 공통으로 빼줘. 다른 것들이 계속 겹치지 않게").

**관련:** D-813(CORE·Fleet Python 사본, 보류) · D-456 · D-483 · D-432 · D-535 · D-370 · D-425

### Context

- Rosy Pilot과 Rosy Cam은 같은 피어 승인 프로토콜(D-456·D-483)을 쓴다. 그런데 Android 코드는 앱마다 사본이었다.
  `PeerProof`/`CameraProof`, `PeerTls`/`CameraTls`는 이름만 달랐다. `AndroidPeerIdentity`/`AndroidCameraIdentity`는 앱 접두어만 달랐다.
- 사본을 맞추는 시험이 없었다. 한쪽만 고치면 서명 바이트·인증서 검증이 앱마다 조용히 달라진다. 그러면 한 앱은 붙고 다른 앱은 안 붙는다.
- Pilot은 이미 Cam 원본 일부(`Pairing.kt`, `PinnedTrust.kt` 등)를 빌드 때 복사해 쓴다. 이 방식은 "Cam이 소유한다"는 뜻이 되어 새 공통 코드가 어디로 가야 하는지 흐렸다.

### Decision

1. **공통 Android 코드는 `shared/android/<영역>/`에 둔다.** 패키지는 `io.github.livsbittt.rosy.<영역>`이다. 앱은 `sourceSets.main.java.srcDir`로 같은 소스를 함께 컴파일한다. 별도 라이브러리 배포·버전은 만들지 않는다.
2. **첫 영역은 `peer`다.** 피어 서명(`PeerProof`), 첫 접촉 CA 고정(`PeerTls`), Keystore 신원(`AndroidPeerIdentity`)을 둔다.
   신원은 `AndroidPeerIdentity(context, app)`이다. `app`("pilot"·"cam")이 기존 키 별칭, 표시 파일, client id 접두어를 그대로 정한다. 그래서 이미 맺은 승인 관계를 잃지 않는다.
3. **앱마다 의미가 다른 것은 앱에 둔다.** 로봇 운전 세션(Pilot `PeerClient`, `PeerRelationshipVault`)과 카메라 자격(Cam `CameraPeerClient`, `CameraRelationshipVault`)은 저장 내용과 수명이 다르다. 공통 조각은 이 코드에서 불러 쓴다.
4. **규칙은 시험으로 지킨다.** `test/architecture/test_app_shared_sources.py`가 다음 세 가지를 검사한다.
   - 각 Android 앱이 `shared/android/peer`를 컴파일하는가.
   - 앱 소스가 공통 타입을 다시 선언하지 않는가. 앱 접두어(`Camera`·`Pilot`·`Cam`)를 붙인 이름도 다시 선언으로 본다.
   - 서로 다른 앱의 제품 소스(`main`·`debug`) 사이에 이름만 바꾼 사본(정규화한 줄 85% 이상 일치, 10줄 이상)이 없는가.

   사본이 필요해 보이면 `shared/android/`로 옮긴다. 기준을 낮추거나 예외 목록으로 덮지 않는다.
5. **웹은 `shared/web/`이 같은 역할을 한다.** 두 화면이 같은 연결·로그인·발견 로직을 쓰면 그곳에 둔다. 이 ADR은 웹의 기존 사본(`function el(...)` 등)을 바로 옮기지 않는다.

### Consequences

- 서명·TLS·신원을 고치면 두 앱이 함께 바뀐다. 두 앱의 단위 시험(`PeerCryptoTest`, `CameraProofTest`)이 같은 코드를 각자의 고정 벡터로 확인한다.
- Pilot이 Cam 경로에서 복사해 오는 기존 공통 파일(`sharedContracts` 작업)은 그대로 둔다. 새로 고칠 때 `shared/android/`로 옮긴다.
- CORE·Fleet의 Python 사본은 D-813이 계속 다룬다. 이 결정은 Android 앱과 웹 화면에 적용한다.
- 실제 태블릿·휴대폰에서 기존 승인 관계가 유지되는지는 설치 후 현장에서 확인한다. 이 ADR은 그 수용을 대신하지 않는다.
