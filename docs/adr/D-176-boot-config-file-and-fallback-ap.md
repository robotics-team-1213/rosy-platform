## D-176 카드의 `rosy-config.yaml`로 기본 설정을 심고, 업링크가 없으면 카드별 비밀번호의 AP를 연다

**Status:** Accepted (2026-09-23). D-154 결정 5(평문 passphrase를 카드에 두지 않는다)와 결정 6(provisioned 장치의
WLAN 장애는 자동 AP 없이 `NETWORK_HOLD`)을 아래 범위로 대체한다. D-26의 `SITE_STA` 기본값과 `RELAY_AP_STA` 옵트인,
D-33·D-154의 장치 신원 규칙은 유지한다.

**Context:** 공식 Pinky OS는 부팅하면 자체 AP(`pinky_XXXX` / 공통 비밀번호)를 열고 LCD에 접속 정보를 띄운다. 그래서
현장 Wi-Fi가 없어도 바로 접속할 수 있다. ROSY는 사정이 다르다.

- 현장 Wi-Fi는 운영 PC의 기록 스크립트가 만드는 일회성 번들로만 들어간다. 카드를 굽고 나면 바꿀 방법이 없다.
  설정을 바꾸려면 카드를 다시 굽거나 SSH로 들어가야 하고, SSH에도 네트워크가 필요하다.
- `deploy/release/network.py`에는 설정 AP·복구 AP·현장 STA 상태 기계가 있지만 네이티브 이미지에 연결되지 않았다.
  첫 부팅은 Wi-Fi에 실패하면 `PROVISIONING_AP`라고 기록만 하고 AP를 열지 않는다(D-174 F-목록 밖의 공백).
- 첫 실기 카드(D-173)는 PC가 다른 네트워크에 있어서 로봇을 찾는 데만 한참 걸렸다.

**Decision:**

1. **설정은 세 층이다. 뒤의 층이 앞의 층을 덮는다.**
   - 이미지 기본값 `/etc/rosy/defaults.yaml`: 비밀이 없고 모든 카드가 같다. 국가 코드, AP 정책, API 포트, 시간대가 들어간다.
   - 개인화 번들 `rosy-provision/provision.json`: 기록 스크립트가 만들고 첫 부팅에 소비한다. 장치 신원, 카드별 AP 비밀번호,
     최초 현장 Wi-Fi가 들어간다.
   - 운영자 설정 `/boot/firmware/rosy-config.yaml`: 사람이 PC에서 열어 고치는 파일이다. 기록 스크립트가 주석 달린 템플릿으로 만든다.
2. **`rosy-config.yaml`은 매 부팅 읽고, 내용이 바뀌었을 때만 적용한다.**
   - 넣을 수 있는 것: Wi-Fi 목록(SSID·비밀번호·우선순위), 국가 코드, AP 정책·SSID, Fleet 주소·trust profile, 시간대,
     운영자 SSH 공개키.
   - 넣을 수 없는 것: 장치 신원(`device_uid`, 이름, 로봇 번호). 신원은 D-33·D-154대로 번들과 재기록(`-ReprovisionReceipt`)으로만 바뀐다.
   - 검증에 실패하면 아무것도 적용하지 않고 직전 설정을 유지한다. 이유는 콘솔 배너와 블랙박스(D-175 L1)에 남긴다.
3. **비밀은 적용 직후 카드에서 지운다(Raspberry Pi OS 방식).** 적용한 Wi-Fi 비밀번호와 사람이 적은 AP 비밀번호는 WPA PSK로 바꿔
   NetworkManager 프로필(0600)에만 남긴다. `rosy-config.yaml`의 해당 값은 `<applied>`로 바꿔 fsync한다. 파일의 나머지 설정은
   그대로 남아 다시 고칠 수 있다. 진단 도구는 이 파일을 비밀 경로로 보고 읽지 않는다(D-175 거부 목록).
4. **업링크가 없으면 카드별 비밀번호의 AP를 연다.** 기본 정책은 `ap.mode: fallback`이다.
   - 현장 Wi-Fi가 하나도 설정되지 않았거나, 설정된 네트워크에 120초 동안 붙지 못하면 `rosy-pinky-xxxx` AP(WPA2, NetworkManager
     shared, `10.42.0.1`)를 연다. 업링크가 돌아오면 닫는다.
   - 비밀번호는 기록 스크립트가 카드마다 랜덤(12자 이상)으로 만든다. 운영 PC의 보호 저장소(DPAPI)와 콘솔 배너에 표시하고,
     이미지·receipt·로그에는 넣지 않는다. 모든 로봇에 같은 비밀번호를 쓰지 않는다(D-33의 공통 기본값 금지).
   - `ap.mode: off`는 D-26/D-154의 `NETWORK_HOLD` 동작, `relay`는 D-26 `RELAY_AP_STA`다. 여러 대가 같이 운용되는 사이트는
     `off`를 권한다. 업링크가 있는 동안 fallback AP는 닫혀 있으므로 정상 운용 중에는 간섭이 없다.
5. **네트워크 제어는 CORE 밖에서 한다(D-161).** 설정 적용과 AP 전환은 root oneshot `rosy-config.service`와 `rosy-network.service`가
   맡는다. 이 둘은 이미 구현된 `network.py` 상태 기계를 네이티브 런타임과 함께 설치해 쓴다. CORE는 상태를 읽기만 한다.
6. **사람에게 보인다.** 부팅 표시(D-174 T0)는 AP가 열려 있으면 콘솔 배너에 AP SSID·비밀번호·주소를 띄우고, avahi TXT에
   `network=ap`를 싣는다. 블랙박스에는 AP 비밀번호를 쓰지 않는다.

**Alternatives:**

- 기록 스크립트만으로 설정: 이미 구워진 카드의 Wi-Fi를 바꿀 방법이 없다(현장에서 가장 흔한 변경이다).
- 비밀이 없는 설정만 편집 가능하게: Wi-Fi 변경이라는 핵심 요구를 못 푼다.
- 공식 OS처럼 모든 로봇에 같은 AP 비밀번호: 한 대의 비밀번호로 모든 로봇에 붙을 수 있다.
- AP 상시 개방: D-26이 기각한 다중 로봇 간섭을 되살린다.

**Consequences:** 카드를 PC에 꽂아 파일 하나만 고치면 Wi-Fi·Fleet·AP 정책이 바뀐다. 첫 적용 전까지 평문 비밀번호가 카드에 있으므로,
그 사이 카드를 잃어버리면 현장 Wi-Fi가 노출된다. 운영자에게 알릴 위험이다. fallback AP 때문에 업링크가 끊긴 로봇도 `10.42.0.1`로
접근할 수 있게 된다. 대신 AP 비밀번호 보관이 새 운영 책임이 된다.

**구현·처리 계획:** [`docs/plans/2026-09-23-boot-config-and-fallback-ap.md`](../plans/2026-09-23-boot-config-and-fallback-ap.md).

**Validation / Transition:** host 계약 시험은 다섯 가지를 확인한다.

- 스키마·검증(신원 필드 거부 포함)
- 적용 후 비밀 삭제(파일에 평문이 남지 않음)
- 잘못된 설정의 무적용
- AP 전환 조건(미설정, 120초 실패, 업링크 복귀)
- 비밀이 receipt·블랙박스에 들어가지 않음

실기에서는 다음을 확인한다.

1. 카드의 `rosy-config.yaml`에 Wi-Fi를 적고 부팅해 연결되는지, 비밀번호가 지워졌는지 본다.
2. 없는 SSID를 적고 부팅해 120초 뒤 AP가 열리고 `10.42.0.1`로 SSH가 되는지 본다.
3. 공유기를 켜서 AP가 닫히는지 본다.
