# OMX 토크 OFF 유한 제한 적용

2026-10-16, D-770 후속. 실제 팔의 무제한 프로파일을 측정 시작용 유한 값으로 바꾸고
각 쓰기 ACK와 실제 readback을 확인했다. 실제 자동 시연과 IL eligible 데이터는 0회다.

## 적용 경로와 검증

`deploy/robot/omx/commissioning_limits.py`는 운영 actuator owner가 아닌 독점 설정 절차다.
기존 register_probe의 persistent by-id·fuser·kernel 독점을 재사용하며, 알려진 여섯 모터의
torque0/error0·mode4(팔)/5(그리퍼)·drive0을 요구한다. 기존보다 커지는 제한은 거절한다.
기존 profile0은 무제한이므로 유한 양의 값으로만 바꾼다. XL430에 전류 레지스터를 쓰지 않는다.

설정 packet 경계는 PWM Limit36/2byte, XL330 Current Limit38/2byte,
Profile Acceleration108/4byte, Profile Velocity112/4byte만 허용한다. 각 쓰기는 정확한
ID·주소·폭·값으로 한 번만 허용한다. 임의 목표·토크·모드·offset·reboot 쓰기는 거절한다.
원본 전체 snapshot과 의도를 fsync한 뒤 송신하며, ACK 성공과 여섯 모터의 실제
readback·다른 설정 보존이 확인된 뒤 다음 쓰기로 진행한다.

ACK 유실·readback 불일치·추가 torque/offset 변화·기록 실패·15초 deadline 초과는
중단한다. 자동 재시도·복원·resume은 없다. uncertain write와 가능한 post snapshot을
보존한다. 동일 output directory는 거절한다. deadline은 durable intent 뒤와 실제
serial write 직전에 다시 검사한다. 독립 검토에서 발견한 fsync 지연 문제를 실제
회귀 RED로 확인하고 수정했다.

| 시험 | 결과 |
|---|---|
| 새 기능 RED | 40개 실패로 미구현 확인 |
| 독립 packet guard RED | 토크/목표/모드/0값 계획 4개 실패 재현 |
| 지연된 fsync RED | deadline 이후 1쓰기 재현 |
| 관련 원격 GREEN | `33fc4c10f`, 65 passed, NEW 0 |
| 독립 source 검토 | deadline 지적 수정 후 material finding 없음 |

수송·ACK·실제 register 상태는 host 시험에서 double이다. 아래 실제 실행은 별도로
동작한 SDK와 장치를 사용했다. 운영 서비스·기존 driver prefix는 바꾸지 않았다.

## 실제 Fleet 설정

고정 source와 request hash를 확인한 별도 private 실행에서 21개 설정 쓰기를 완료했다.
264개 PING/READ packet과 21개 cap write가 실제 송신 trace에 있다. 모든 cap write는
계획한 값과 순서가 같고 다른 write instruction은 없었다. 각 쓰기마다 ACK와 실제
readback을 확인했고 마지막 독립 raw snapshot도 일치했다. 전후 여섯 모터 torque0/error0이다.

| 대상 | 설치한 값 | 의미 |
|---|---|---|
| 여섯 모터 PWM Limit | raw20 | 출력 상한 약2.26%, EEPROM |
| XL330 세 모터 Current Limit | raw50 | 약50mA, EEPROM; current-based 그리퍼에는 전류 상한 |
| 여섯 모터 Profile Velocity | raw1 | velocity-based profile의 약0.229rev/min, RAM |
| 여섯 모터 Profile Acceleration | raw1 | 약214.577rev/min², RAM |

원본 PWM885·XL330 Current1750과 profile0을 전체 snapshot에 보존했다. PWM/Current
상한은 전원 재시작 후에도 남는 설정이다. 자동 복원하지 않았으며 적용된 낮은 값을
계속 유지한다. RAM profile은 재시작 뒤 반드시 다시 읽어야 한다. 이 값은 측정 시작용
설계 선택이며, 물리적 도달·부하 유지·안전한 작업 범위의 실측값은 아니다.

제조사 [XL330](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/)와
[XL430](https://emanual.robotis.com/docs/en/dxl/x/xl430-w250/)의 단위·적용 mode·profile0
의미를 확인했다. XL430은 전류 레지스터가 없어 PWM 상한을 사용한다. 팔 XL330의
extended-position mode도 PWM 상한을 사용하며 Current Limit만으로 전류 제한을
확정하지 않는다. 버스 watchdog을 독립 stop으로 간주하지 않는다.

Goal Position은 cap 검증의 불변 설정에 포함하지 않았다. 앞선 독립 읽기 전용 관찰에서
목표·현재 위치가 함께 1틱 변했음을 이미 확인했기 때문이다. 모든 원본 값은 보존하며
이번 결과를 이전 goal 보존 검사 실패의 해소로 기록하지 않는다.

## 실제 native 시작 목표, 토크 OFF

같은 8-patch native driver와 새 보존형 candidate를 사용한 별도 probe에서 첫 fresh
torque0/error0 read 뒤 실제 on_activate/start를 한 번 호출했다. 여섯 GPIO의 Torque
Enable/Reboot 선택을 모두0으로 검사했기 때문에 enable list는 비어 있다. start는
상태 read→joint command 동기화→초기 목표 쓰기만 수행했고 torque enable은 없었다.
controller/operational owner의 trajectory를 기동한 시험은 아니다.

실제 loaded library/hash·device identity·독점 guard·유한 cap을 실행 전에 확인했다.
native init/start와 정상 소멸은 exit0이었다. 시작 전후 fresh 상태 message3회에서 여섯
torque0/error0을 확인했고 독립 raw 전후 snapshot의 cap·mode·offset 등은 같았다.

송신107개는 PING6·READ12·indirect SRAM mapping84·FastBulkRead4·SyncWrite1이다.
SyncWrite는 indirect Goal Position 주소224/폭4에 ordered IDs11..16의 목표 한 묶음만
보냈다. native 첫 read의 nominal raw 위치와 목표는 최대1틱 차이였다. float→integer
변환의 양자화와 읽기 사이 위치 변화의 기여를 각각 분해한 시험은 아니다.
토크·reboot·mode·offset 변경 packet은 없었다.

목표 차이2틱 기준은 **송신 후** 저장 packet 분석으로 검사했으며 사전 transport guard가
아니다. 이 단계가 토크 OFF이고 모든 enable 선택이0임을 유지한다. SyncWrite의 송신
성공을 모터 ACK·물리 도달·정지 성공으로 기록하지 않는다. torque OFF에서 목표/현재
위치의 1틱 변화는 이전 관찰과 함께 원본에 남겼고 goal 불변성을 주장하지 않는다.

실제 code/loader/trace/output은 별도 private
`~/rosy-test/omx-first-target-torque-off-33fc4c10f/`에 보존했다. `source-and-run.json`은
새 장치 접근 없이 저장 자료만 hash로 묶고 목표 차이·판정 범위를 기록했다. 같은
디렉터리는 재실행하지 않았다. 독립 source 검토에서 이 토크 OFF 범위의 추가 지적은 없었다.

## 원본과 남은 일

Fleet private `~/rosy-test/omx-commissioning-caps-33fc4c10f/`에 고정 source·요청·
expected hash, `before.json`, `after.json`, `wire.trace`, `execution.json`과
`attempt-01/events.jsonl`/`receipt.json`이 있다. full hash는 이 receipt가 소유한다.
원격 시험 로그는 호스트 외부 `rosy-il-python312/commission-*-{red,green}`에 보존했다.

토크 ON·실제 움직임·독립 stop·부하 검수는 실행하지 않았다. 실물 owner/HOLD/terminal·
독립 정지 관측·두 영상과 실제 동작의 동기 기록을 이어서 연결한다.
