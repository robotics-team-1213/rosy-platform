# RaspTank Metal / Pi 4 사전 준비

2026-10-25 기준. 목표는 Ubuntu Server 24.04 arm64 + ROS 2 Jazzy + systemd에서
공통 ROSY를 실행하고 RaspTank 전용 어댑터로 하드웨어를 연결하는 것이다.
현재는 `rasptank_metal`의 **설정 소스만 준비**되어 있다. 실행 드라이버, native 설치,
ROSY 통합 SD 이미지, 센서·구동·팔의 실물 수용은 아직 없다.
[호환 상태](../reference/robot-compatibility.md)와 [통합 설계](../plans/2026-10-25-rasptank-multi-robot-design.md)를 함께 본다.

## 준비할 부품

| 구분 | 품목 | 수량·선택 기준 |
| --- | --- | --- |
| 기본 | Raspberry Pi 4 Model B | 4GB 기준. 보유 8GB도 사용 후보. 영상 인식 부하는 서버 분산부터 검토하고 실제 지연·열·메모리로 판단 |
| 기본 | microSD와 리더 | 128GB A2를 우선 검토하되 쓰기 수명·제조사 보증도 확인. microSDXC 리더 1개, 비교·복구용 카드 1개 권장 |
| 기본 | 벤치 전원 | Pi 4용 USB-C 5V/3A급. HAT 전원과 동시 공급은 회로·역급전 확인 전 금지 |
| 기본 | 방열·절연 | Pi 4용 낮은 방열판, HAT 높이에 맞는 스탠드오프·절연 받침. 팬은 부하 시험 후 결정 |
| 동봉 대조 | HAT·카메라·케이블·센서·서보·모터·홀더 | 아래 표와 실제 출고 구성표 대조. 같은 부품을 미리 중복 구매하지 않음 |
| 조건부 | 18650 셀과 충전 수단 | 동일 모델·상태의 셀 2개 후보. 홀더 길이·단자·보호회로·방전 정격·보드 충전 방식 확인 후 선택 |
| 공용 | 멀티미터·자/캘리퍼·LAN·공유기 | 전압·극성·차체/관절 실측, 초기 네트워크 복구용. 기존 장비 우선 |
| 후속 | 독립 정지/출력 차단부 | HAT의 출력 유지·enable 동작과 팔 낙하 위험 확인 후 설계. Python 정지 호출만으로 독립 정지 충족으로 보지 않음 |

IMU·LiDAR·encoder·추가 USB 카메라는 초기 무구동 인식 확인을 위한 필수 구매품이 아니다.
지도 주행이 필요하면 위치 추정·궤도 미끄럼·선회 보정을 포함해 선택한다.
초음파와 라인 센서만으로 Pinky의 지도 주행 기능이 확보되지는 않는다.

## 동봉 장치와 연결·수용 조건

아래 주소와 핀은 제조사 고정 소스의 조사값이다. 실물 배선 지시나 자동 탐색/출력 명령이 아니다.
HAT 개정판과 연결도를 확인한 뒤 사용한다. 모든 센서는 현재 ROSY capability에서 미광고 상태다.

| 장치 | 조사된 연결·소프트웨어 | ROSY 연결과 첫 확인 |
| --- | --- | --- |
| 카메라 | 제조사 `Server/camera_opencv.py`는 Picamera2/libcamera 사용. 정확한 센서 모델 미확정 | Pi 4의 CSI 15핀에 맞는 케이블·접점 방향 확인. 전원 차단 상태로 장착. Bookworm 기준 영상과 Ubuntu 실제 캡처를 각각 확인 |
| 초음파 | `Server/ultra.py`: BCM trigger 23, echo 24, gpiozero. 반환값은 cm | HAT echo 레벨 변환 회로 확인. ROS Range에는 m로 변환하고 timeout/무응답은 미관측으로 처리. 알려진 거리·무응답·분리 시험 |
| IR 라인 3채널 | `examples/07_TrackingLine.py`: BCM 22/27/17. 변수와 InputDevice의 좌우 연결이 교차 | 실물 왼쪽/중앙/오른쪽을 따로 가려 방향·극성·흑백 응답 기록. Pinky 보정값을 복사하지 않음 |
| 전압 ADC | `Server/Voltage.py`: ADS7830 가정, I2C 0x48 | 실제 칩·분압·채널을 회로와 대조하고 멀티미터와 비교. 제조사 전압/잔량 식을 검증 없이 SOC로 광고하지 않음 |
| OLED | `Server/OLED.py`: I2C bus 1, 0x3c, SSD1306/luma | 보드 개정·해상도 확인 후 표시 시험. 디스플레이 오류가 정지 경로를 막지 않도록 분리 |
| 부저·LED | gpiozero 예제. 부저 예제는 BCM18 표기 | 실제 보드 핀·능동/수동형을 확인. 상태 표시용이며 안전 정지 수단으로 취급하지 않음 |
| DC 모터 | `Server/move.py`: PCA9685 0x5f, 50Hz, throttle PWM | 전용 어댑터의 단일 writer·명령 만료·정지 경로가 필요. PWM을 m/s로 간주하지 않으며 채널·극성은 바퀴를 띄운 상태에서 보정 |
| 팔·집게·카메라 서보 | `Server/RPIservo.py`: 같은 PCA9685 0x5f/50Hz | 모터와 버스/출력 소유권 조정. 실제 서보·각도 제한·부하·초기 자세 확인. 코드의 명령 위치를 측정 관절값이나 파지 성공으로 보내지 않음 |
| IMU·encoder·LiDAR | 기본 제공과 동작 경로 미확인 | 필요 기능을 정한 뒤 부품·인터페이스·전원 예산 선정. Pinky의 센서 이름이나 capability를 복사하지 않음 |

카메라는 먼저 동봉품을 사용한다. Ubuntu에서 센서 드라이버·libcamera/Picamera2 경로가
확보되지 않으면 원인을 확인한 뒤 UVC USB 카메라를 대안으로 선정한다.
제조사 Bookworm 앱의 성공이 Ubuntu/Jazzy 성공을 뜻하지 않는다.
기존 `middleware/perception/front_camera`의 입력·캘리브레이션 경계를 재사용하되,
RaspTank용 캡처 backend·서비스 연결은 아직 없다. 카메라 높이·방향·렌즈·왜곡·노출,
프레임 시각·해상도·영상 지연·CPU 부하를 실측한 다음 인식 기능을 올린다.

## SD 이미지 준비 상태

다운로드 산출물은 저장소 밖 작업 공간의
`Rosy/artifacts/2026-10-25-rasptank-pi4-preparation/`에 보관한다.
`README.md`, `preparation.json`, `verification.md`, `LOCAL-SHA256SUMS`에 출처·해시·검사 범위를 남겼다.
이 로컬 경로는 배포 URL이나 저장소에 포함된 파일이 아니다.

| 산출물 | 준비·검사 | 용도와 남은 조건 |
| --- | --- | --- |
| Ubuntu 24.04.5 Server arm64+raspi | 공식 SHA256·서명 확인, XZ 전체 해제 검사·파티션 서명 확인 | ROSY 목표 OS 원본. ROS/Jazzy·ROSY·기체 어댑터가 합쳐진 이미지 아님 |
| Raspberry Pi OS Bookworm arm64 desktop 2026-10-06 | 공식 체크섬/Imager 메타데이터 대조, XZ·파티션 검사 | 제조사 기능을 분리 확인할 비교용. ROSY 제품 OS 아님 |
| Adeept ADR034 자료와 고정 GitHub 소스 ZIP | 다운로드·로컬 SHA256·ZIP CRC 확인 | 배선/조립/드라이버 조사용. 배포 이미지나 HAT 플래시 바이너리 아님 |
| ROSY 통합 이미지·서명 manifest | 미생성 | native ARM64 빌드·패키지 설치 closure·모델 결속·이미지 검증이 선행되어야 함 |
| SD 기록·readback·Pi 부팅 | 미수행 | 대상 카드 식별, 유효한 이미지와 삭제 대상 확인 후 별도 수행 |

Ubuntu 원본 SHA256:
`b23371a5c8d02f612c26e7c18cacb81c5a48f968c7c66a2645391320aa94351e`.
Bookworm 압축 이미지 SHA256:
`5f7a98229d8e3290c93b1409d8a2973cb8b96807504f1626269ef07b7439d8af`.

운영 카드와 제조사 비교용 카드는 분리하고 identity·키·네트워크 비밀을 공개 이미지에 넣지 않는다.
Pinky SD writer/이미지 preset은 RaspTank 지원이 없다. 모델명을 Pinky로 바꾸거나 manifest 검사를
우회해서 기록하지 않는다. Pi 4 EEPROM은 실물 revision·현재 버전·공식 요구 조건 확인 후 판단한다.
사전 EEPROM 업데이트나 HAT 펌웨어 플래시는 수행하지 않았다.

## 기체 도착 후 순서

1. Pi RAM/revision, HAT 버전, 카메라 센서, 서보 수·종류, 배터리/충전 회로와 배선을 사진·부품표로 대조한다.
   현재 상품은 HAT V3.3, 배포 PDF는 V3.2 표기가 있어 출고품을 기준으로 확정한다.
2. 전원·극성·절연·CSI 케이블을 확인한다. 처음에는 구동/서보 출력을 분리하고 Pi만 벤치 전원으로 부팅한다.
3. 비교용 카드에서 제조사 장치 인식과 카메라를 확인하되 자동 구동 서버/부팅 서비스를 켜지 않는다.
   제조사 설치 스크립트는 실행 전 자동 시작·GPIO·패키지 변경을 검토한다.
4. 목표 Ubuntu에서 카메라·GPIO·I2C 접근과 native ARM64 ROSY 패키지 설치를 검증한다.
   선택 모델·설치 패키지·실제 읽힌 profile/capabilities를 결속하고 Pinky 절대경로 overlay 잔존을 거절한다.
5. 센서별 단위·방향·오류/단절·시각을 기록한다. 무구동 상태의 identity·인증·상태·관제 연결부터 수용한다.
6. 전용 어댑터와 독립 정지를 구현한 뒤 모터·서보의 단일 writer, 통신 단절, 만료 명령,
   프로세스 종료, 전원 재투입 시 무구동을 확인한다. 팔은 지지하고 관절별 제한을 보정한다.
7. 제한된 조작부터 기능별로 수용하고 해당 capability만 활성화한다.
   지도 주행·복귀·군집·자동 파지는 추가 센서/위치 추정과 별도 수용 뒤에 검토한다.

공통 ROSY에서는 identity·인증·명령 수명·상태·관제를 재사용한다. Base 최종 명령은 CORE,
Fleet 입장/작업 기록은 Fleet, 팔 action은 기존 장치 owner 경계를 유지한다.
기체별 I/O 차이는 어댑터가 담당하며 UI의 기종 분기로 하드웨어 차이를 감추지 않는다.

## 근거

- [제조사 제품·동봉 구성](https://www.adeept.com/adeept-rasptank-metal-smart-robot-car-kit-for-raspberry-pi-5-4b-3b-3bboard-not-included-tank-tracked-robot-with-4-dof-robotic-arm-opencv_p0436_s0100.html)
- [제조사 ADR034 배포 자료](https://www.adeept.com/learn/detail-85.html)
- [조사 고정 소스 e60a17a](https://github.com/adeept/Adeept_RaspTank_Metal/tree/e60a17a59185a86abfdd67828364185c4011bb22)
- [Ubuntu Raspberry Pi 이미지](https://cdimage.ubuntu.com/releases/24.04/release/), [서명 검증 안내](https://ubuntu.com/tutorials/how-to-verify-ubuntu)
- [Pi 4 공식 제원](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/)
