# D-914 장치별 프로필과 native 운용범위 근거를 연결한다

**Status:** Accepted (2026-10-29, 사용자 구현·커밋·머지 지시). 소프트웨어 연결의 결정이며 장치 배포·실측 수용은 별도다.

## Context

D-911은 실제 팔 설정/보정과 전체 작업을 구분하지만 Fleet의 장치 프로필과 연결되지 않았다. D-860의 안정된 `device_id`는 설명 정보이며 동작 권한이나 접속 확인이 아니다. D-907의 signed component profile은 공유 소프트웨어 정의이므로 로봇 신원으로 사용하지 않는다. LeRobot 설정에는 임의의 프로필 필드를 추가할 수 없다.

## Decision

운영자가 설치한 로컬 JSON `rosy.omx-cell-robot-profile.v1`을 별도로 선택한다. 새 장치 DB·Fleet API·owner·bus writer를 만들지 않는다.

| 필드 | 의미 |
|---|---|
| `schema` | `rosy.omx-cell-robot-profile.v1` |
| `device_id` | D-860 장치 정보의 안정된 ID. 연관 관계이며 접속·동작 수용 근거는 아님 |
| `instance_id` | 기존 recorder `robot.id`와 같은 팔 인스턴스 |
| `robot_config_sha256` | 기존 recorder 전체 `robot` 객체의 canonical JSON SHA. ID·by-id port·구동/카메라 설정 포함 |
| `operating_envelope_path` | 선택한 장치의 검토 manifest |
| `work_dir` | 선택한 장치의 시도 장부와 pending intent 위치 |

1. 빈 ID/경로·미완성 SHA·중복 JSON key·authority 필드는 거절한다. 상대 경로는 프로필 위치를 기준으로 해석한다. **실제 절대 경로로 정규화한 문서**를 프로필 SHA로 삼아 다른 디렉터리에 복사한 옛 장부의 재사용을 막는다. 같은 실제 경로의 별칭은 같은 SHA다. 검토 내용은 해시에 넣지 않아 task/runtime SHA와 순환하지 않는다.
2. `record_session --chunks/--replay --operating-profile`은 recorder의 instance/config를 bus 접근·cap 변경 전에 검증한다. `~`를 확장한 같은 절대 경로를 사용하며 chunks child와 session receipt에 binding을 전달한다.
3. `chunk_runner`는 hardware import/connect 전에 같은 검증을 한다. runtime context에 device/instance/config/profile binding을 넣고 실제 readback·보정·코드 SHA도 유지한다. 기존 프로필 없는 수동 세션은 자동 파지 근거가 아니다.
4. `cell_pipeline --operating-profile` 또는 `operating_profile_path`로 같은 프로필을 선택한다. work/review 경로는 프로필이 정한다. 자동 작업 외에 감독 survey·coarse/reset·복구의 raw 이동도 FIFO client가 현재 profile·신선한 상태를 확인하고 checked session/library 명령으로 보낸다. 다른 팔이면 상태 조회 외 명령을 보내지 않는다. 프로필 없는 기존 명시적 수동 recovery 정책은 유지한다.
5. record stage는 실제 하달할 recorder robot을 카메라·폴더·subprocess 작업 전에 검증하고 replay 세션에도 같은 선택을 전달한다.
6. envelope manifest는 `device_id`, `instance_id`, `profile_sha256`를 고정한다. task key·시도·summary에도 binding을 남겨 같은 모델명이나 library만으로 다른 로봇의 검증을 재사용하지 않는다. 빈 예제는 장치 바인딩·자동 허용을 만들지 않는다.
7. runner가 실제 사용할 검증된 매개변수 전체를 시작 전에 한 번 읽고 같은 값을 runtime SHA와 실행기에 전달한다. 접촉·pacing·idle 값 변경은 기존 task 검토를 재사용할 수 없으며, 파일이 없어 적용한 기본값과 같은 명시적 기본값은 같은 신원이다. `cell_params.py`도 코드 SHA에 포함한다. client의 별도 params 파일이나 경로·설명 메타데이터를 실제 runner 값의 대용으로 쓰지 않는다.
8. 배치 성공 판정에 사용하는 `verify_tol_mm`도 유효 기본값 10.0 mm를 정규화해 task 조건 SHA에 포함한다. 판정과 해시는 같은 유한·비음수 검증 함수를 사용한다. 값이 바뀌면 기존 검토를 재사용하지 않는다.
9. 자동 파지 client가 실제 선택한 명령 순서를 Gate와 executor에 같은 값으로 전달하고 task 조건에 넣는다. 같은 library라도 직선 운반과 접은 운반은 서로의 검토를 사용하지 않는다. client의 유효 params도 기본값을 정규화해 함께 고정하고 실제 순서·호출을 소유하는 cell_transfer.py와 cell_auto_pick.py를 코드 SHA에 포함한다.
10. 검토 후 현재 시도가 만든 durable pending intent는 삭제하거나 전역으로 무시하지 않는다. 같은 config·보정·순서·library와 현재 라이브 세션의 automatic load만 이미 검토한 근거로 checked 전송한다. 새 Gate는 기존 pending에서 시작할 수 없고, 경로·조건 변경은 다시 평가해 거절한다. 감독 모드의 재계획과 시도 소유자가 완료 행을 기록한 뒤 pending을 해제하는 절차는 유지한다.

Fleet의 이름·모델 수정은 운용범위 승인이 아니다. 이 연결은 Fleet DB의 실시간 접속 확인을 구현하지 않는다. 운영자가 ID 연관 관계를 명시하며 물리 신원·설치·카메라 보정·하중은 기존 owner/검증 절차로 수용한다. task별 물체·높이·카메라·경로와 D-911 보호 조건은 계속 검사한다.

## Verification

합성 A/B 프로필의 instance·port/config 불일치, 잘못된 manifest/상태, 감독 이동·record 우회, 같은 경로 별칭과 다른 장부 위치, 검토 내용 비순환성, parent→child 전달, hardware-free import를 회귀 시험한다. 원격 소프트웨어 시험은 실물 프로필 설치나 실제 가동범위의 수용 근거가 아니다.
