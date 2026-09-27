# LCD 얼굴 G2/G3 후속 회차 — 2026-09-27

## 범위와 판정

표면은 `src/hmi/face`의 320×240 가로 LCD 카드다. 질문은 지나가는 사람이 로봇의 현재 의도와 주의·위험을 알아볼 수 있는가다(D-153 §2, concept 16 §7.4). 이번 회차는 Windows의 ROS 없는 PIL 렌더만 실행했다. **LOCAL 부분 증거, LCD 표면 판정 HOLD**다. 실물 LCD 사진, `hold_s` 만료 후 의도 GIF 복귀, 거리·각도·조명 판독성이 없다. 호스트 이미지가 BENCH/DEVICE 또는 FIELD 증거는 아니다.

기준: `main`의 `ca3b3869`에서 시작한 `fix/lcd-uiux` 작업 트리, D-153·D-221·D-306. 생성 스크립트와 PNG 9개는 일회성 `X:\DevTemp\rosy-uiux-d306-lcd-g2\`에만 있다. 스크립트 `render_g2.py`는 가짜 ID·AP 키·IP를 써서 `render()`·`render_boot()`를 직접 호출한다. `python -X utf8 X:\DevTemp\rosy-uiux-d306-lcd-g2\render_g2.py`로 현재 호스트에서 다시 만들 수 있다. X:가 지워지면 캡처도 사라지므로 보존형 전체 G2 완료 증거로 세지 않는다.

## G1과 렌더 환경

`PYTHONPATH=src/hmi/face`와 `ROSY_FACE_CAPTURE_DIR=X:\DevTemp\rosy-uiux-d306-lcd-g2`를 설정하고 아래 명령을 실행했다.

```powershell
python -X utf8 -m pytest src/hmi/face/test/test_info_screen.py src/hmi/face/test/test_info_screen_boot.py src/hmi/face/test/test_info_screen_palette.py src/hmi/face/test/test_wifi_qr.py src/hmi/face/test/test_info_screen_capture.py src/hmi/web/test/test_shared_controls.py -q -p no:cacheprovider
```

결과는 **148 passed, 5 warnings**다. 경고 5개는 기존 캡처 시험의 Pillow `Image.getdata()` 사용 중단 예고다. 생성된 9개 이미지는 모두 RGB 320×240이고 배경과 다른 픽셀의 경계가 이미지 안에 있다. Windows에서 `_font(16)`의 실제 이름은 **Aileron Regular**다. 대상 Linux/Pi의 후보는 `DejaVuSans-Bold.ttf`/`DejaVuSans.ttf`이므로 이 호스트 캡처로 대상 글꼴의 행간·글리프·거리 판독성을 증명할 수 없다.

## G2 상태 매트릭스 — 호스트 PIL

아래 파일명은 모두 `X:\DevTemp\rosy-uiux-d306-lcd-g2\` 아래에 있다. 캡처에서 문장, 잘림, 색 배치, 값의 정직성을 육안 확인했다. `ink_bbox`는 배경색과 다른 픽셀의 경계이며 `(left, top, right, bottom)`이다. 우측 가장자리의 AP QR은 x=316까지 쓰되 320을 넘지 않는다.

| 셀 | 파일명 (`*_320x240_local.png`) | 관찰 | `ink_bbox` |
|---|---|---|---|
| 최초 기동·빈 값 | `01_first_boot` | `BOOTING`, `no IP address`, `battery --`, `release ?`; 주의·위험색 없음 | `(17,11,307,154)` |
| 정상 값 표본 | `02_nominal_ready` | `READY`, 주소, `87% 8.21 V`; 주의·위험색 없음. 이 정지 이미지만으로 freshness를 증명하지는 않음 | `(17,12,307,150)` |
| 주의 | `03_warning_caution` | `45%`, ADC 주의·다음 조치가 주황색/본문으로 구분되고 실패 빨강은 없음 | `(17,12,307,191)` |
| E-STOP 스냅숏 | `04_estop` | `HEALTH E-STOP`이 위험색 채움+밝은 글자; 주소 줄과 겹치지 않음 | `(16,15,305,229)` |
| 주소 없음 | `05_network_missing` | 기동 카드가 `no IP address`를 명시; 이것은 네트워크 `disconnected` 판정이나 라이브 로봇 연결 증거가 아님 | `(17,12,307,150)` |
| 긴 동적 값 | `06_long_strings` | ID·MODE/NAV/HEALTH·주소에 말줄임, 우측 여백 유지; 기존 5개 필드 회귀 시험도 통과 | `(16,13,305,227)` |
| 배터리 결측 | `07_battery_missing` | 퍼센트와 전압이 `--`, 빈 게이지, 위험색 없음. 결측을 0%로 표시하지 않음 | `(16,15,305,229)` |
| AP 접속 | `08_ap_join_demo` | 주소·SSID·예시 키와 QR이 서로 겹치지 않음. QR 내용과 디코딩은 `test_wifi_qr.py`/부팅 시험의 호스트 계약만 확인 | `(16,12,316,220)` |
| 기동 실패 | `09_failed_unit` | `FAILED`, `rosy-core`, 낮은 배터리, 실패 문장이 위험색 채움으로 구분됨 | `(12,12,307,173)` |

빠진 셀: `delayed`/`disconnected`/`unavailable`의 별도 LCD 배지는 이 표면의 계약이 아니다. concept 16 §5는 웨이크 정보 카드가 `hold_s` 후 사라져 의도 화면으로 돌아가게 하며, 없는 배터리는 `--`로 표시한다. 이번 정지 이미지는 **만료·복귀 시간, CORE 중단 후 재수신, 화면 백라이트**를 관찰하지 못했다. `E-STOP` 캡처는 상태 스냅숏이고 물리 `SAFE_STOP` readback이 아니다. 얼굴에는 입력과 확인 대화상자가 없어 확인 취소/승인 셀은 비해당이다.

## D-153 G3 8항 근거

| 항목 | 이번 근거와 현재 판정 |
|---|---|
| 1. 정직 | `01`, `05`, `07`: 없는 IP·배터리를 각각 문장/`--`로 표시하고 배터리 위험색을 쓰지 않는다. 입력 조작은 없다. **LOCAL 충족**. |
| 2. 증거 상태 | `07`의 결측과 concept 16 §5의 만료·복귀 계약을 확인했다. 실제 `hold_s` 경과 및 통신 단절 시 오래된 카드 제거는 미관찰. **BENCH 보류**. |
| 3. 색 | `02` 정상은 무채색, `03` 주의는 주황, `04`·`09` 위험은 빨강 채움이며 팔레트 계약 시험 통과. 적록 색각·1.5m·조명 판독성 미관찰. **BENCH 보류**. |
| 4. 위계 | `02`의 상태·주소·배터리, `03`의 다음 조치, `09`의 실패 단위가 한 카드에서 구분된다. 이 표면에는 조작 버튼이나 복수 카드가 없다. **LOCAL 충족**. |
| 5. 불가역 | 얼굴 LCD에는 입력 API·확인 대화상자가 없다(`emotion_server.py`의 수신·표시 경로). E-STOP은 읽기 전용 상태다. **N/A**. |
| 6. 어휘 | D-221이 MODE/NAV/HEALTH 기계 약어와 DejaVu 의존을 고정한다. `04`의 `E-STOP`, `03`의 주의 문장은 호스트에서 읽히지만 행인 대상 무문자 채널은 실물 확인 필요. **계약 충족, BENCH 판독 보류**. |
| 7. 표면 질문 | `01`·`02`·`03`·`04`·`09`에서 의도·주의·위험의 문장과 형태가 달라진다. 실제 GIF 복귀, 1.5m·0.5초 식별이 없어 질문의 최종 답은 미확인. **BENCH 보류**. |
| 8. 표면 문법 | 320×240 단일 카드에 입력 없이 상태 스냅숏을 그린다. concept 16 §7.4의 예외인 웨이크 카드와 만료 후 의도 GIF 복귀는 코드 경로로만 확인, 실물 관측은 없음. **LOCAL 부분 충족, BENCH 보류**. |

G3은 호스트 근거를 채운 기록이며 사람·장치 최종 수용이 아니다. 기존 F-07 어휘 결정은 D-221에서 약어 유지와 비문자 채널의 실물 질문으로 정리됐다. 따라서 이번 회차에서 임의로 라벨을 번역하거나 폰트를 추가하지 않는다.

## DEVICE/BENCH 판정에 필요한 실물 회차

1. 장치 모델·LCD 해상도/회전·실행 이미지 digest·폰트 파일(`DejaVuSans*`)·촬영 날짜를 사진 기록과 묶는다. 배포 이미지에 face가 실려 실제 `display/info`와 `rosy-boot-display`가 실행되는지 별도 확인한다.
2. 실제 LCD 정면 **1.5m**와 **0.5m**에서 `BOOTING`, 정상, 주의, `FAILED`, E-STOP, 배터리 결측, AP QR 화면을 촬영한다. 1.5m에서는 **0.5초 이내 한 번 보는 동안** 의도·위험을 구별할 수 있는지 관찰하고, 0.5m에서는 작은 주소·단위·말줄임을 확인한다. 각 화면의 정면과 좌우 약 30°에서 반사·잘림을 기록한다.
3. 낮은 조도 **100–300 lux**와 밝은 작업장 **500–1000 lux**를 목표 조건으로 두고 실제 LCD 표면 위치의 조도(lux)를 기록한다. 카메라는 디지털 줌 없이 원본 사진을 남기며 촬영 거리·각도·노출·백라이트 모드를 함께 적는다. 파일명은 예를 들어 `lcd_failed_front_1p5m_low-bench.jpg`처럼 상태·거리·각도·조명을 포함한다. 이 조도 범위는 새 합격 임계값이 아니라 재현 조건이다.
4. 실제 CORE 입력으로 `display/info`를 띄운 후 기본 `hold_s` 15초와 명시적 짧은 값에서 **카드 만료→의도 GIF 복귀**를 영상/시각 기록한다. CORE 송신 중단·배터리 결측·주소 상실의 표시를 관찰하고, E-STOP/SAFE_STOP의 물리 상태와 LCD 메시지를 별도 대조한다.
5. AP가 열린 실물 LCD의 QR을 iPhone/Android 기본 카메라로 **10–25cm**에서 읽고, 수기 SSID/키 입력도 확인한다(D-272). QR에도 키가 들어 있으므로 원본 사진은 제한된 보관소에만 두고 공개본에서는 QR과 키를 모두 가린다. 실제 키를 로그·문서에 적지 않는다. 장치 사진과 관찰 결과가 있을 때만 G3 #2·#3·#6·#7·#8과 DEVICE/BENCH를 다시 판정한다.
