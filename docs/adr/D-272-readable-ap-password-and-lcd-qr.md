## D-272 AP 비밀번호는 로봇마다 다르되 읽기 쉬운 형식과 LCD QR로 보여준다

**Status:** Accepted (2026-09-26). D-176 결정 4의 "비밀번호는 기록 스크립트가 카드마다 랜덤(12자 이상)으로 만든다"와
D-190의 AP 표시 내용(`Wi-Fi <SSID>`·`PW <비밀번호>` 두 줄)을 아래로 개정한다. 로봇마다 다른 비밀번호(D-176, D-33의
공통 기본값 금지)와 표시·보관 규칙(LCD에만 그리고 로그·블랙박스·API·receipt에 넣지 않는다)은 그대로다.

**Context:** fallback AP(D-176)와 설정·복구 AP(`deploy/release/network.py`)의 생성 비밀번호는 대소문자·숫자를 섞은
무작위 문자열(기록 스크립트 14자, `network.py` 20자)이었다. 사람이 LCD에서 읽어 폰에 치기 어렵다. `l`/`1`/`I`,
`O`/`0`이 섞이고, 폰 키보드에서 대소문자와 숫자를 계속 바꿔야 한다. 공식 Pinky OS처럼 모든 로봇에 같은 쉬운
비밀번호를 쓰면 입력은 편하지만 한 대의 비밀번호로 모든 로봇에 붙는다. D-176이 이미 기각한 대안이다.

**Decision:**

1. **생성 형식은 `rosy-xxxx-xxxx`다.** 접두어 `rosy-`와 4자씩 두 묶음이다. 문자는 소문자와 숫자에서 헷갈리는
   `0 o 1 l i`를 뺀 31자(`abcdefghjkmnpqrstuvwxyz23456789`)다. 전체 14자다(WPA2 하한 8자 이상).
   - 설정 AP·복구 AP: `deploy/release/network.py`의 `generate_setup_psk`(`secrets.choice`). relay AP는 로봇이 켜져 있는 동안 계속 열리고 사람이 입력하지 않으므로 4묶음(`groups=4`, 약 79비트)을 쓴다(리뷰 반영).
     형식은 `READABLE_SETUP_KEY`.
   - 카드별 fallback AP: `deploy/sd/prepare-rosy-sd.ps1`의 `Get-ApPassword`(`RandomNumberGenerator`, 248 이상 바이트는
     버려 문자마다 확률이 같다).
   - 이미 DPAPI 저장소에 있는 카드의 비밀번호는 다시 구울 때 그대로 재사용한다. 새 형식은 새 카드부터다.
   - 사람이 `rosy-config.yaml`의 `ap.password`에 적은 비밀번호는 지금처럼 받는다(형식 제한 없음, 번들은 12-63자).
2. **엔트로피는 무작위 8자뿐이다.** 31^8 ≈ 8.5×10^11, 약 39.6비트다. 접두어 `rosy-`는 고정이라 엔트로피가 0이다.
3. **위협 판단.** AP를 엿들은 사람이 WPA2 핸드셰이크를 잡아 오프라인으로 푸는 경우를 기준으로 한다. GPU 한 장이
   초당 약 250만 PSK를 시험하면 31^8 전체는 약 34만 초(약 4일), 기대값은 그 절반(약 2일)이다. 사용자는 이 수준을
   받아들였다. `rosy-` + 5자(31^5, 약 11초)는 기각했다. 근거:
   - fallback AP는 업링크가 없을 때만 잠시 열리는 설정용 네트워크다(D-176: 120 s 뒤 열고 600 s마다 비켜 선다).
     AP 너머에는 CORE API 인증(D-191/D-193)이 따로 있다.
   - 로봇마다 다르므로 한 대를 풀어도 다른 로봇에는 소용이 없다.
   - 더 긴 비밀번호가 필요한 사이트는 `rosy-config.yaml`에 직접 적는다.
4. **LCD는 AP가 열려 있을 때 Wi-Fi 접속 QR을 함께 그린다(D-190 개정).** 내용은 `WIFI:T:WPA;S:<ssid>;P:<psk>;;`이고
   `\ ; , : "`는 역슬래시로 이스케이프한다. 폰 카메라로 찍으면 입력 없이 붙는다.
   - 위치: 머리줄 아래 오른쪽, 흰 바탕 검은 모듈, quiet zone 2모듈. 모듈당 4 px인 버전 4 코드가 148 px(2.4인치
     패널에서 약 22 mm)이다. 옆의 줄(단계·주소·배터리·상태)은 왼쪽 칸으로 줄어들고, `Wi-Fi <SSID>`·`PW <비밀번호>`는
     코드 아래 전체 폭에 그대로 남아 손으로도 칠 수 있다.
   - AP가 닫혔거나 SSID·비밀번호를 모르면 그리지 않는다. 버전 5(84바이트)를 넘는 긴 SSID·비밀번호는 글자만 보인다.
   - QR 문자열과 행렬은 비밀번호와 같은 규칙을 따른다. LCD에만 그리고 로그·블랙박스·API·파일에 쓰지 않는다.
     `secret_scan`은 `WIFI:…;P:<psk>;;` 모양도 비밀로 잡는다(`wifi-qr`).
5. **QR 인코더는 직접 쓴다.** 장치 이미지(`deploy/image/device-python-requirements.txt`, D-189)와 벤더 apt 목록에는 QR
   인코더가 없다. 고정된 작은 코드 하나를 위해 해시 고정 휠을 추가하지 않는다. `src/hmi/face/emotion/wifi_qr.py`는
   바이트 모드, 오류 정정 M, 버전 1-5만 하는 순수 Python 인코더다. ISO 형식 비트 표, Reed-Solomon 공개 벡터(HELLO WORLD
   1-M), 고정 행렬, OpenCV 디코드 왕복으로 시험한다.

**Alternatives:**

- 모든 로봇에 같은 쉬운 비밀번호: 한 대의 비밀번호로 모든 로봇에 붙는다. D-176·D-33이 금지한다.
- `rosy-` + 5자: 입력은 더 쉽지만 핸드셰이크를 잡으면 약 11초에 풀린다.
- 기존 대소문자 혼합 14자 유지: 엔트로피는 높지만(약 81비트) 사람이 읽고 치기 어렵다는 문제를 못 푼다.
- QR만 보여 주고 비밀번호 글자는 숨김: 카메라로 QR을 못 읽는 기기(노트북)가 붙을 수 없다.
- QR 라이브러리(segno·qrcode) 추가: 장치 런타임에 휠·해시·라이선스 관리가 하나 늘어난다.

**Consequences:** 폰은 QR로, 노트북은 14자 소문자 비밀번호로 붙는다. 비밀번호 엔트로피는 약 81비트에서 약 40비트로
줄어든다. 위협 판단(결정 3)이 그 대가를 받아들인 근거다. 이미 구운 카드는 재기록 전까지 옛 형식을 쓴다.
AP가 열린 동안 LCD의 상태 줄은 좁아진 왼쪽 칸에 맞춰 글자가 작아지거나 말줄임된다.

**Validation / Transition:** host 시험은 형식·문자 집합·엔트로피·호출마다 다름(`test/test_network_provisioner.py`),
기록 스크립트 형식(`test/test_sd_writer_contract.py`), 비밀 스캔(`test/test_ap_psk_secret_scan.py`), QR 인코더
(`src/hmi/face/test/test_wifi_qr.py`), 부팅 카드의 QR 유무·디코드(`src/hmi/face/test/test_info_screen_boot.py`),
표시 루프가 키와 QR을 로그에 남기지 않음(`test/test_boot_display.py`)을 본다. 실기에서는 다음을 확인한다.

1. 현장 Wi-Fi 없이 켜서 AP가 열리면 LCD에 QR과 `PW rosy-xxxx-xxxx`가 함께 보이는지.
2. iPhone·Android 기본 카메라로 LCD의 QR을 찍어 AP에 바로 붙는지(거리 10-25 cm, 화면 반사 포함).
3. 노트북에서 LCD 글자를 보고 비밀번호를 쳐서 붙는지.
4. 업링크가 돌아와 AP가 닫히면 QR이 사라지는지. `journalctl -b -u rosy-network -u rosy-boot-display`에
   비밀번호와 `WIFI:`가 없는지.
