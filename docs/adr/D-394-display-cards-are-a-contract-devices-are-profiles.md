## D-394 화면 카드는 계약이고 장치는 프로파일이다 — 주행 카드와 전자잉크 예약

**Status:** Accepted (2026-10-01, 사용자 요청·위임). 재사용 단위는 `display/info` 페이로드 계약이고, 장치가 그리는 법은 프로파일 하나로 말한다.

잇는 결정: [D-385](D-385-rosy-expresses-itself-mode-faces-and-breathing-boot.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-190](D-190-vendor-parity-boot-display.md) · [D-315](D-315-folder-role-is-not-writer-authority.md).

### Context

LCD 카드 체계는 이미 절반 나뉘어 있었다: CORE의 `bridge/display.py`가 **무엇을** 보일지(페이로드)를 정하고, `emotion/info_screen.py`가 **어떻게** 그릴지를 안다. 그러나 ①주행 중에는 데이터가 안 보였다 — 정보 카드는 근접·배터리 웨이크에만 뜨니, 로봇을 따라가는 운용자에겐 얼굴 GIF만 보였다. ②장치가 Pinky라고 굳어 있었다 — 크기·색·숨쉠 무늬가 한 파일에 박혀 있어 다른 기기(전자잉크 등)는 복제해야 했다.

### Decision

1. **재사용 단위 = 페이로드 계약.** 카드 종류는 `display/info`의 `kind` 필드로 구분한다(없으면 웨이크 카드 — 호환). `render_card`가 단일 입구로 디스패치하고, 계약 시험이 픽셀로 지킨다. 새 장치는 **같은 페이로드**에 자기 렌더러를 붙인다.
2. **장치는 `DisplayProfile` 하나로 말한다**: `name`·`size`·`animation`. 색은 모듈의 토큰 사본(D-82/D-194)이 유일한 출처 — 장치마다 팔레트를 새로 정의하지 않는다. `animation=False`(전자잉크: 부분 갱신이 느림)는 프레임을 무시하고 고정 카드를 그린다. `PINKY_ST7789`(320×240)가 첫 프로파일.
3. **주행 카드(`kind: "drive"`)**: 운용 중(MANUAL·NAVIGATION·DOCKING·EMERGENCY — IDLE 제외)에만 **20 s마다 5 s** 동안 얼굴 위로 지나간다(`display.drive_due`·`drive_payload`, ROS-free). 큰 모드 단어 하나·속도 한 줄·내비게이션·배터리 게이지 — 1 m 밖에서 따라가는 사람이 읽는 카드다. 반올림은 웨이크 카드와 같은 계약(0.01 m/s), 결측 속도는 None이다(0.00은 '멈춤'으로 읽힌다).
4. **발행 경로는 기존 `display/info` 퍼블리셔를 쓴다** — 토픽·구독 수 변화 없음. IDLE에 얼굴이 주인인 건 그대로다(표정은 기분이고 카드는 일이다).

### Alternatives

- **장치별 카드 파일 복제:** 여섯 달 뒤 여덟 개의 디버전전 카드. 거부.
- **주행 카드 상시 표시(얼굴 대체):** 얼굴이 사라진 로봇은 제품이 아니다. 주기적 지나감이 차분하다(D-280). 거부.
- **속도를 큰 글자로:** 운용자는 이미 로봇 속도를 눈으로 안다; 카드가 말해야 하는 건 '어떤 모드로 움직이는가'다. 거부.

### Consequences

`display/info` 페이로드가 사실상 다중 소비자 계약이 된다 — 종류·필드 변경은 호환적으로. 전자잉크 렌더러는 이 결정이 예약한 자리다(구현 없음, 하드웨어 없음). 주행 카드의 케이던스(20 s/5 s)는 운용 피드백으로 조정한다.

### Validation

- 계약 시험(호스트): `drive_due`(IDLE/None 부재, 20 s, EMERGENCY 포함), `drive_payload`(kind·반올림·결측 None), `render_drive`(모드·속도·결측 픽셀), `render_card` 디스패치(픽셀 동일/상이), 전자잉크 프로파일 프레임 무시. 변이 증명 2종(EMERGENCY 제외→빨강, 디스패치 절단→빨강 — 픽셀 단정 강화 후).
- 기기(다음 릴리스): NAVIGATION/MANUAL 중 20 s마다 카드 지나감 확인.
