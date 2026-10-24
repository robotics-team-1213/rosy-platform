# RaspTank Metal을 공통 ROSY에 연결하는 설계안

상태: 설계 제안 v2, 문서 등록. 2026-10-25. 기준 소스: rosy-platform `26499b1f51546072cd1edce7068ed489bc54b0e2`. 새 ADR·API·실물 지원 승인을 대신하지 않는다.

후속 준비: 무구동 설정 패키지 소스를 추가하는 단계다. 아래 기준 소스에서의 부재 설명과 실제 후속 상태는 구분하며, 최신 상태는 [호환 목록](../reference/robot-compatibility.md)과 해당 모듈 progress를 따른다. 제품 활성화 결속·드라이버·이미지·실물 수용은 여전히 별도다.

## 이번에 준비할 결과

1. 공식 Ubuntu 24.04 LTS Raspberry Pi arm64 OS 이미지, 서명된 checksum, 고정된 Adeept 소스·설명 자료를 확보한다. 순정 OS를 ROSY 통합 이미지로 부르지 않는다.
2. 플랫폼 README에서 연결하는 호환 목록 변경안을 만든다. RaspTank Metal / Pi 4B 4GB는 지원 후보이며 아직 실행 가능한 robot package가 아니다.
3. PINKY·RaspTank·OMX가 공통 ROSY 기능을 쓰는 경계와 단계별 구현·검증 계획을 남긴다. 현 단계에서는 드라이버·API·명령 권한을 바꾸지 않는다.

이 문서는 지원 후보와 단계별 구현 조건을 기록한다. 실행 가능한 기체 package, 공개 API, 명령 권한과 실물 수용 상태를 변경하지 않는다. [호환 목록](../reference/robot-compatibility.md)이 기종별 현재 상태의 안내다.

## 근거와 기존 경계

- `docs/adr/D-14-.md` Accepted: 로봇별 차이는 Profile과 Driver Adapter로 격리하며, 두 번째 로봇에서 필요한 인터페이스만 다듬는다.
- CORE SRS HWA-001/002/003: 프로파일이 기능 선언의 원천이며, 신규 기체는 어댑터로 연결한다. CAP-003은 미지원 명령에 명확한 거절을 요구한다.
- `contracts/foundation/core_common/profile.py`: 모델 기반 조회는 ament share 또는 `middleware/devices/*/profile`을 선택하며 조회 실패 시 오류다. 다만 `middleware/core/gateway/core/node.py:46`은 절대경로 profile/capability를 모델 조회 없이 사용하며, `test_core_node_robot_paths.py:68`이 이 호환 동작을 보존한다. 따라서 미설치 모델의 제품 기동 차단은 현재 코드만으로 보장되지 않는다. RaspTank 제품 시작 검증에서 선택 모델·설치 package·프로파일·capability의 결속을 별도로 확인해야 한다.
- `middleware/devices/pinky/profile/config/`는 현재 실제 존재하는 구성이다. `middleware/devices/rasptank`는 아직 없다.
- `contracts/foundation/core_common/protocol/controls.py`: `rosy.controls/1`에 base_velocity, bounded joint_jog, gripper가 있다. 단위·범위·상태 의미는 그대로 유지한다. 현재 gripper schema는 기본 readback을 position/grasp로 표현하므로 피드백 없는 서보에 그대로 광고하지 않는다.
- README 핵심 계약: CORE만 최종 Base `/cmd_vel`을 발행한다. Fleet이 승인·dispatch·원장을 소유하고 World는 현재 관측·자세를 제공한다. 기존 OMX joint/action owner를 CORE의 새 PWM writer로 대체하지 않는다.
- D-856 Accepted: 업무 앱은 업무 의미를 소유하고, ROSY는 중립 동작을 접수·조정하며 장치 owner가 최종 출력·안전·실제 결과 근거를 소유한다. 상세 구현과 실물 수용 완료를 뜻하지 않는다.
- D-161 Accepted: 제품은 Ubuntu Server 24.04 arm64 + Jazzy + systemd. 제품 이미지에 Docker를 요구하지 않는다.
- `deploy/robot/pinky_pro/image/AGENTS.md`: native aarch64 빌드·오프라인 패키지·이미지 검증이 필요하다. 현재 Pinky 전용 입력·필수 패키지를 RaspTank로 이름만 바꾸지 않는다.
- 제조사 고정 소스 `e60a17a59185a86abfdd67828364185c4011bb22`: 모터·서보가 동일 PCA9685 I2C 0x5f / 50Hz에 접근한다. 배타적 I/O owner와 출력 정지 검증이 필요하다. encoder·관절각 피드백은 확인되지 않았다.

## 공통 기능과 기체별 구현

공통으로 유지할 것은 인증·등록·identity, 상태·장애·이벤트, 명령 식별과 만료, 실행/attempt 결과, capability 협상, 관제·Pilot의 제어 위젯, 이미지 버전·업데이트·복구 규칙이다. 같은 ROSY를 쓴다는 것은 이 계약과 동작 의미를 공유하는 것이다. 모든 기체가 같은 기능을 제공하거나 같은 SD 바이트 이미지를 사용한다는 뜻은 아니다.

기체 프로파일에는 물리 구성·확인된 센서·속도/관절 범위·실측 보정·설치 패키지와 드라이버 선택을 둔다. 장치별 I/O에는 UART/I2C/GPIO·서보 펄스·센서 프로토콜·독립 정지를 둔다. 알고리즘과 공통 CORE에 `if RaspTank` 분기를 추가하는 것으로 이 경계를 대신하지 않는다.

Pinky의 Dynamixel encoder 속도·RaspTank의 PWM 출력·OMX의 관절 명령은 각각 다른 어댑터에서 구현한다. 외부 명령이 m/s·rad라면 어댑터가 검증된 변환을 해야 하며 PWM duty를 측정 속도로 반환하지 않는다. 변환이 검증되지 않은 단계에서는 해당 운영 제어를 광고하지 않고 no-motion 진단만 제공한다. 센서가 없는 기체에는 그 기능을 숨기고 같은 기능을 호출하면 미지원으로 거절한다.

팔이 달린 RaspTank는 Base와 Arm 자원 점유를 함께 고려해야 한다. 공통 실행 계층은 기체·자원 identity와 취소·정지·실패·불명 상태를 다루고, RaspTank의 팔 owner/어댑터가 실물 관절·토크·집게를 맡도록 후속 계약을 검토한다. 기존 OMX 드라이버에 RaspTank 채널을 주입하거나, CORE에 두 번째 관절 출력을 추가하지 않는다. 이번 문서만으로 새 팔 owner를 활성화하지 않는다.

## 호환 목록의 의미

호환성 문서는 한 곳에서 기종·컴퓨터·구동부·센서·실행 profile 존재·이미지·실물 근거를 분리한다. `candidate`는 자료 조사와 구현 대상 등록이고 `accepted`와 다르다. 소스가 존재하는 Pinky/OMX도 기능별 SOURCE/ARTIFACT/DEVICE/FIELD 증거를 따로 본다. 어떤 기존 기체도 이 표 작성만으로 실물 수용 상태가 올라가지 않는다.

RaspTank의 첫 행은 Pi 4B 4GB, Ubuntu 24.04 arm64/Jazzy 목표, tracked skid-steer + servo arm, profile/driver/image 미구현, 실측·실물 수용 미수행으로 적는다. Pi 5는 제조사 지원 조합이지만 우리 Pi 5 경로도 별도 검증 대상이다. 추정 URDF는 visualization-only로 표시하고 차체 반경·충돌 회피·계획·제어에 등록하지 않는다.

## 이미지·펌웨어 구분

- 지금 확보하는 Ubuntu `.img.xz`: 서명·해시를 확인한 순정 OS 후보. ROSY·Jazzy 앱·RaspTank 프로파일은 포함하지 않는다.
- 후속 ROSY 통합 이미지: 공통 OS/런타임/복구 층 + 기체별 검증된 패키지 closure + 기체별 최초 부팅 프로비저닝. `rasptank_metal` 실행 패키지가 설치되지 않았으면 선택을 거절한다.
- 기체별 Wi-Fi·키·ID·보정값은 공통 공개 이미지에 넣지 않는다. RaspTank를 Pinky 번호와 복제하지 않는다.
- Pi EEPROM/부트 펌웨어는 OS와 별도 상태다. OS manifest에 들어 있는 rpi-eeprom 패키지를 기록하되 자동 flash/recovery를 실행하지 않는다. 보유 Pi revision·현재 EEPROM을 확인한 뒤 공식 필요 조건에 따라 판단한다.
- 현재 확인한 HAT 코드에는 사용자가 flash할 HAT firmware 산출물이 없다. 실제 보드에 별도 MCU가 있으면 식별·공급사 절차부터 확인한다. PCA9685 제어 코드를 MCU firmware라고 부르지 않는다.

## 비교한 대안

1. **공통 CORE + capability/profile + 전용 어댑터:** 기존 계약을 재사용하고 기능 차이를 명시할 수 있다. 선택안이다. 어댑터·피드백·보정·이미지 closure는 실제로 구현해야 한다.
2. **Pinky 이미지·설정을 복제하고 기종명만 변경:** 빠르게 파일을 만들 수 있지만 Dynamixel/카메라/센서/보정·정지 기능을 오인하므로 제외한다.
3. **제조사 웹 제어를 ROSY 제품 제어와 병행:** 하드웨어 비교용 단독 실행은 유용하다. 동일 HAT 동시 writer와 공통 승인·기록 우회가 발생하므로 운영 구성으로 쓰지 않는다.

## 구현 단계와 수용 기준

### A. 지금 가능한 준비

다운로드한 순정 OS의 공식 signer fingerprint·SHA256·크기·출처를 기록한다. 제조사 자료는 upstream 서명 여부와 로컬 hash를 구분한다. 호환성 문서를 README에서 연결하고, 후보 등록과 실행 지원을 구분한다. 문서 링크·harness와 해당 커밋의 원격 문서 계약 시험을 확인한다. 문서 등록을 기체 구현이나 실물 수용으로 보고하지 않는다.

### B. 후속 no-motion 통합

후속 구현에서는 `middleware/devices/rasptank/profile` 패키지를 추가하는 작업을 별도 커밋으로 다룬다. `robot.model=rasptank_metal` 선택이 실제 설치된 ament share를 읽는지 확인한다. 제품 시작 검증은 선택 모델·설치 package·프로파일·capability의 일치와 근거를 확인하고, 미설치·잘못된 모델은 무구동으로 실패해야 한다. 특히 RaspTank package가 없는 상태에서 Pinky의 절대경로 profile/capability를 남긴 사례와 package는 있지만 파일 내용이 Pinky인 사례를 검사한다. 절대경로 설정의 기존 개발·배포 호환성을 일괄 삭제하는 대신 제품 activation의 결속 검증을 검토한다. no-motion에서 motion/arm/navigation/grasp 기능을 광고하지 않는다. CORE·Pilot의 비기종 분기 경로가 유지되는지 확인한다.

검증 위치: `contracts/foundation/test/test_robot_selection.py`, `middleware/core/gateway/test/test_core_node_robot_paths.py`, 기체 profile 패키지 시험, `contracts/foundation/test/test_controls_contract.py`. 구체 변경 전에 현재 메서드·schema·호출 경로와 기존 시험을 읽고 원격 red/green을 수행한다. 로컬 Windows pytest로 대체하지 않는다.

### C. 후속 I/O와 제어

새 기체 I/O는 실제 HAT/채널/회로 검증 후에 구현한다. 운영 motion 활성화의 진입 조건은 독립 정지 수단, 최대 정지 지연, Pi hang·전압 강하·PCA9685 출력 유지 때의 실제 출력 상태, 팔 지지·hold/전원 차단 동작을 기록하고 검증하는 것이다. 충족하지 못하면 no-motion을 유지한다. 유효 명령 상한·NaN/Inf 거절·만료·재시작 무구동·단일 writer·I2C 오류·관절 한계를 시험한다. Pi OS 정지는 systemd 복구와 별도로 다룬다. 추정 metric odom/관절 측정/파지 완료를 만들지 않는다.

팔·그리퍼 제어 광고 전에는 약속한 위치·파지 상태의 실제 피드백과 완료 판정 근거가 있어야 한다. command-only actuator를 쓰려면 측정/명령 상태와 완료 의미를 구분하는 계약을 별도로 검토·시험해야 한다. 기존 gripper readback의 position/grasp 기본값을 그대로 사용하는 것으로 이 조건을 충족하지 않는다.

명령 손실·서비스 종료·Pi hang·전원 sag, 부팅 중 서보 기구 간섭, 관절 상태 미확인, 장치 응답 후 네트워크 timeout을 실패 시나리오로 둔다. timeout 후 동일 물리 명령을 무조건 재발행하지 않는다. 실제 동작 수용은 사람 있는 기체 시험으로 별도 확인한다.

### D. 후속 제품 이미지

Pi 4가 실행 가능한 native ARM64 빌드와 검증된 패키지 inventory를 확보한다. 빌드 host가 ARM64라는 사실만으로 Pi 4 CPU·드라이버 호환이 증명되지는 않는다. 기존 Pinky 입력을 우회하지 않고 기체별 required package·boot 설정·프로비저닝을 분리한다. 기존 이미지 코드를 옮기는 대규모 재편은 재사용 경계가 확인된 부분만 수행한다.

mount/package/unit/서명·해시 검사, 카드 write/readback, 실기 부팅, 무구동 복구, 독립 정지를 순서대로 검증한다. 실패 시 이전 승인 이미지/카드와 보정값으로 복귀하되 기존 기체 ID를 임의 덮어쓰지 않는다. RaspTank용 signed image가 검증되기 전 Pinky writer의 model 선택에 넣지 않는다.

## 검증 및 변경 권한

이번 변경은 문서 등록이다. 커밋한 뒤 저장소 규칙의 `tools/remote/remote_pytest.py`와 문서 harness 검사를 수행해야 한다. 원격 검사 불가·기존 NEW 실패는 제품 착지·push를 막는다. 장치 접근·SD 기록·모터 동작·펌웨어 flash는 이번 파일 준비에 포함하지 않는다.

리뷰 상태: 독립 1차 검토에서 critic은 준비 단계 A를 승인했고 architecture는 절대경로 overlay 우회에 대한 제품 시작 검증 보강을 요청했다. v2는 해당 검증과 독립 정지·팔 피드백 진입 조건을 추가했다. 독립 2차 검토에서 architecture와 critic 모두 준비 범위와 문서 변경안에 남은 중대 지적이 없다고 확인했다. 이 리뷰는 제품 코드·계약·실물 수용 승인을 대신하지 않으며 B–D 구현은 미수행이다.
