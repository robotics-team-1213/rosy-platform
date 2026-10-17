# 스테이션 충전 실습 준비와 현장 수용

대상은 스테이션 한 개와 이동 로봇 한 대다. 시뮬레이터 실행은 사용자 요청으로 제외했다. 이 문서는 현장 확인을 위한 준비 절차이며, 장치 활성화 승인이나 실제 운행 완료 기록은 아니다. 현장 담당자가 나중에 확인할 수 있다는 기존 응답을 유지한다.

## 현재 상태

2026-10-17 소스 `e5f51f5c7`(초기 구현 `ba4868ef59`)는 원본 배터리 계측과 전체 작업 창의 에너지 제한을 private native 경로에 연결했다. 이후 `57a136d87`은 Fleet 실제 앱 조립에서 실측 건강도 정책을 요구한다. `65a26cbd61`의 에너지·지도·native 실행·충전 정책/복구 합동 CPU 회귀는 공식 원격 모델 PC에서 696 PASS/0 skip/NEW 0이다. 이는 전체 CI·ROS 실제 기동·장치 수용을 뜻하지 않는다. 정확한 범위와 실패 수정 과정은 [새 검증 기록](../validation/station-measured-health-2026-10-17/result.md)을 따른다.

Fleet의 기존 `charge_runtime_factory`는 `MeasuredChargePolicyAdmission`을 runtime과 service의 동일 인스턴스로 제공해야 한다. `measured_sources`에는 로봇별 승인된 측정 종류와 capacity revision을 설치 근거에서 결속한다. 해당 값과 SOH·Wh·온도가 없으면 자동 정책을 허용하지 않는다. 이 등록은 실제 공급자 인증·교정 승인·장치 연결을 만들어내지 않는다. 기존 voltage-only exporter를 임의 수치로 보완하지 않는다.

기존 `build_station_owner`는 현재 `runtime_mode != 'simulation'`인 구성을 거절한다. 원본 BMS/fuel-gauge 공급자 어댑터와 승인된 하드웨어 프로필, 실제 hardware factory 및 Fleet→CORE HTTP 전체 연결이 남아 있다. 설정에서 `enabled`를 켜거나 runtime 문자열을 바꾸어 이 경계를 우회하지 않는다.

## 시작 전 기록

다음 표를 실제 현장에서 채운다. 없는 장비는 ‘없음’, 읽지 못한 값은 ‘미확인’으로 남긴다. 주소·토큰·비밀번호·개인 키는 공개 저장소에 기록하지 않는다.

| 항목 | 기록할 근거 | 현재 수용 상태 |
|---|---|---|
| 대상 | robot/station ID, 실제 장비 라벨, CORE boot ID, 설치 release SHA, 현장 확인자와 시각 | 현장 확인 필요 |
| 연결 | 승인된 기존 SSH 경로, Fleet↔CORE 연결, 최신 원본 위치와 수신 시각 | 기존 오래된 위치는 재사용 불가 |
| 런타임 | 실제 CORE Python/ROS 버전과 command owner, downstream watchdog | 새 제한의 지원 대상은 CPython 3.12/GIL, 장치 런타임은 별도 확인 |
| 지도·접근 | map ID/revision, station pose revision, 실제 접근 공간·귀환 경로와 불확실성 | 관제 표시 맞춤은 제어 좌표 근거가 아님 |
| 카메라 | 렌즈·방향·조명, 원본 frame sequence/time, source ID/epoch, 교정 revision과 상대 위치 오차 | 기존 거의 검은 상부 영상은 정상 관측으로 수용 불가 |
| 배터리 | 실제 pack ID, BMS/계측기 모델, 원본 sequence/time, 용량 교정 revision, 사용 가능 Wh 하한, SOC/SOH·온도·fault | 전압 기반 표시 잔량으로 대체 불가 |
| 충전기·접점 | 실제 장비 모델, 착좌/하중 접점, 충전 보고, 정상/고장/접촉 상실 종료 신호와 원본 시각 | 설치·신호 사양 미확인 |
| 물리 한계 | 전체 장치 전력 상한, reserve, 허용 온도/SOH, 제동·coasting·출력 지연·watchdog 상한 | 제조사 조건과 실측 수용 필요 |

연결·등록은 [기존 SSH 안내](robot-ssh-access.md), 영상/관제는 [천장 카메라 운영 가이드](site-ceiling-camera-console-runbook.md), 실제 장치 입회와 관측은 [Pinky 입회 절차](pinky-pro-attended-session-runbook.md)를 따른다. 키 재등록·서비스 재시작·배포·모터 활성화를 단순 상태 확인과 섞지 않는다.

## 운행 전 확인 순서

1. 대상 한 대와 스테이션, 실제 boot/release를 대조한다. 최신 영상과 위치 원본을 확보한다. 관제에서 좌표가 보인다는 사실만으로 현재 위치를 확정하지 않는다.
2. 카메라·로봇·스테이션의 실제 좌표 변환과 교정을 확인한다. 기존 `StationObservation`은 `base_link` 상대 위치, 원본 시각, source epoch, 교정 revision, map/pose revision에 결속한다. 오래된 관측을 새 receipt 시각으로 갱신하지 않는다.
3. `StationPoseRecord`의 검증된 접근 위치와 Fleet/CORE의 같은 pose revision ACK를 확인한다. 지도에 접근·귀환 가능한 공간과 실제 station 방향이 맞아야 한다.
4. 원본 에너지 공급자가 실제 pack/교정 revision을 증명하는지 확인한다. 전체 장치 전력에는 ZERO/대기·센서·컴퓨팅·재시도·정지 tail을 포함한다. 테스트의 숫자를 장치 한계로 복사하지 않는다. source와 Ledger는 같은 trusted monotonic clock을 사용해야 한다.
5. 순시 전압·높은 SOC·충전 이벤트 하나로 작업을 승인하지 않는다. Fleet의 작업/귀환 비용, CORE의 원본 에너지·native/map/odom 근거와 실제 귀환 가능성을 모두 확인한다. 측정이 없거나 만료되면 대기한다.
6. 물리 정지·접점·충전 종단 신호를 원본부터 후속 처리까지 연결한 실제 조립 경로를 검증한다. 현재 없는 vendor 어댑터나 hardware factory가 이미 설치됐다고 가정하지 않는다.

원본 수신 속도와 유효기간은 CORE의 동시 유효 energy receipt 상한 8개와 함께 검토한다. 초과하면 닫히는 구현이다. 실제 공급자 속도/유효기간의 진행성을 수용하기 전 자동 반복 운행을 열지 않는다. source/parent를 재생성하거나 이력을 지워 상한을 우회하지 않는다.

## 실제 한 주기의 수용

각 단계에 원본 evidence 시각·identity·revision과 관제 세션/원장 기록을 남긴다. 로봇 움직임이 포함되는 단계는 기존 입회 절차와 현장 확인이 가능해진 뒤 실행한다.

| 순서 | 확인할 결과 | 진행을 막는 조건 |
|---|---|---|
| 복귀 승인 | 현재 station/map/pose revision, 예약·작업·귀환 비용과 새 parent의 원본 에너지 승인 일치 | 결측·만료·revision 불일치·귀환 경로 불명 |
| 상대 접안 | 기존 CORE 접안 제어기에 최신 상대 위치가 전달되고 실제 오차가 장치 프로필 안에 있음 | 시야/교정/원본 위치 상실, 불확실성 초과 |
| 착좌·정지 | `SeatingEvidence`의 실제 접점/하중·위치·heading·측정 선속도/각속도가 신선하고 설정된 유지/디바운스 창 충족 | 명령 ACK나 ZERO만 있고 물리 정지/착좌 근거 없음 |
| 후속 처리 | 착좌와 물리 정지 이후에만 충전/후속 작업 인계, 상실 시 기존 차단 경로 동작 | 착좌 전 작업·로봇 암 인계 또는 미확정 정지 |
| 충전 중 | 도크 보고와 팩 전압의 기존 충전 확인 경로 유지, 안전 신호 상실 즉시 해제 | 전압만으로 안전 경로 억제, 접점 상실·fault |
| 정상 완료 | 현재 세션 이후 charger/BMS의 `NORMAL` 종료와 신선한 허용 팩 전압 근거 | `charging=false`만 있거나 오래된 완료·고장/접촉 상실 |
| 이안·재투입 | 측정 정지/종료 경계 뒤 새 에너지·작업 승인과 새 parent로 이안·재투입 | 만충 이벤트만으로 출발, STOP된 parent 복구, 예산/원본 시각 reset |

같은 로봇·스테이션에서 복귀→접안→착좌/정지→충전 정상 완료→이안/재투입을 **3회** 확인한다. 첫 성공만으로 연속 운행 수용을 주장하지 않는다. 긴 충전 대기는 이전 parent의 수명을 늘리지 않는다.

## 스테이션 위치가 바뀌었을 때

1. 이전 위치의 실행을 기존 exact-session/parent 정지·종료 경계로 닫는다. 실제 정지·종료를 확인하기 전 새 목표를 겹쳐 발행하지 않는다.
2. 카메라도 움직였다면 교정을 새로 확인한다. 같은 카메라 ID와 오래된 교정을 근거로 위치를 확정하지 않는다.
3. Fleet이 새 map/pose revision과 검증된 접근 위치를 확정하고 CORE가 같은 revision을 ACK하는지 확인한다. 지도 표시 맞춤값을 제어 좌표로 가져오지 않는다.
4. 새 귀환 경로·현재 원본 위치·불확실성·에너지와 새 admission을 확인한 뒤 복귀한다. 실제 이동 후 위치·방향 오차와 착좌 결과를 별도로 남긴다.

## 결과 기록

실제 원본 위치/교정, pack/충전기 사양, 각 주기의 세션과 정지·착좌·정상 종료 증거, 위치 변경 전후 revision/ACK, 측정 오차와 프로필 한계를 `docs/validation/`의 새 날짜 기록에 연결한다. 정적 검토, Python 시험, 실제 장치 동작, 현장 정밀도는 각각 구분한다. 미실행 항목과 원인이 남아 있으면 자동운행 활성화 또는 전체 목표 완료로 기록하지 않는다.
