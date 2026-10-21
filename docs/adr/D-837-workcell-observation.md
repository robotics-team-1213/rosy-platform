## D-837 Fleet 작업 셀의 읽기 전용 관측과 화면 연결

**Status:** Accepted for implementation (2026-10-21).

### Context

두 follower와 상단·손목 세 카메라의 실제 관측은 가능하지만 현재 도구는 별도 localhost 진단 화면이다. Fleet에는 ROS 토픽을 등록 관측으로 전달하는 producer와 물리 관절 표시 경로가 없다. 개발 PC의 SSH 연결이나 SIM owner 활성화를 제품 관측의 전제로 두면 안 된다.

### Decision

Fleet PC의 native ROS subscriber가 두 팔과 세 카메라를 구독한다. 이 프로세스는 serial을 열거나 명령을 발행하지 않는다. Fleet 서버와 브라우저는 ROS를 사용하지 않는다. 관절은 인증된 Fleet 최신 관측 cache로, 영상은 기존 Vision ingress·preview lease로 전달한다. 기존 `/console/cell` 화면에서 관측을 보여 주며 문서 compiler·motion owner의 활성화와 독립적으로 작동한다.

명시적 private manifest `rosy.workcell-observations/1`은 workcell, arm source/board/topic/ordered joint names와 camera source/topic/arm 관계를 등록한다. 관계는 설정된 대응이며 기구 보정이나 command instance 등록을 뜻하지 않는다. producer마다 독립 credential의 환경 변수 이름만 manifest에 저장한다. Fleet read 응답에는 secret·serial path를 넣지 않는다. preview-only 카메라 등록은 map·marker·calibration 객체를 만들거나 sighting 권한을 주지 않는다.

Manifest는 `{schema:"rosy.workcell-observations/1",workcells:[{workcell_id,label,arms:[{source_id,arm_id,label,board_id,joint_topic,joint_names,token_env}],cameras:[{source_id,label,role,arm_id,image_topic,device_path,token_env}]}]}`이다. `role`은 `overhead` 또는 `wrist`, overhead의 arm_id는 null, wrist는 같은 workcell의 등록 arm_id다. Device selector는 camera의 `/dev/v4l/by-id/` 또는 `/dev/v4l/by-path/` direct child, board_id는 OpenRB 일련번호이며 native serial source binding에 쓴다. Joint topic은 `/omx_commissioning/<label>/joint_states`, image topic은 절대 `.../image_raw`다. Unknown fields와 command topic, 중복 source/topic/device/board/arm/joint, 빈 목록·중복 credential은 거절한다. Workcell/source/arm ID는 ASCII `[A-Za-z_][A-Za-z0-9_-]{0,63}`, joint names는 `[A-Za-z_][A-Za-z0-9_]{0,63}`, token_env는 uppercase environment name이다. Workcell 최대32, 셀당 arm/camera 각8, 팔당 joint 최대8, label 최대80자와 제어문자 금지로 입력·메모리를 제한한다. 예시에는 실제 장치 식별자나 secret을 넣지 않는다.

API v1.295는 다음 관측 전용 경로를 정의한다.

- `GET /api/fleet/workcell-observations`: 기존 Fleet viewer 인증으로 등록 workcell 목록과 팔별 latest snapshot, camera source metadata를 읽는다. `{read_only:true, physical_acceptance:false, workcells:[{workcell_id,label,arms:[{source_id,arm_id,label,units:"encoder_rad",fresh,epoch,sequence,captured_at,source_age_s,receipt_age_s,positions}],cameras:[{source_id,label,role,arm_id}]}]}`. 미수신은 sequence0·epoch/captured_at/age/positions null, 만료는 positions null이다. 실제 시운전 보정 좌표로 해석하지 않는다. no-store.
- `POST /api/fleet/workcell-observations/arms/{source_id}`: `X-Workcell-Observation-Token`으로 해당 등록 source만 수신한다. body는 `{epoch,sequence,captured_at,positions}`만 허용한다. epoch는 producer 시작마다 새 UUID hex32, sequence는 advancing positive integer, captured_at은 원본 UNIX seconds, positions는 등록 joint 집합과 정확히 같은 finite JSON number mapping이다. 성공 202 `{accepted:true}`; 미등록/잘못된 credential401, replay·역행·미래/만료 원본409, 구조 오류422, 기능 미설정503. Payload는 workcell·board·arm identity를 선택하지 못한다. body limit16KiB.

서버는 source별 최신 sample 하나와 retired epoch 최대64개만 메모리에 둔다. 서버 재시작은 cache를 비우며 원본 재생으로 복원하지 않는다. 같은 epoch의 sequence는 증가해야 하며 captured_at은 epoch 변경에도 마지막 accepted capture보다 증가해야 한다. 새 epoch의 첫 sequence는1이며 보존 중인 retired epoch는 거절한다. 재시작과 retired history 제거 후 모든 과거 요청을 식별한다고 보장하지 않으며 원본 age 제한을 계속 적용한다. Capture age는 수신 시 -0.25..2초, 표시 시에는 원본 age와 서버 monotonic receipt age 모두 최대2초다. 거절된 update는 마지막 정상 sample을 덮어쓰지 않는다. HTTP 재수신은 원본 capture를 fresh로 만들지 않는다.

기존 calibrated/static/paired source와 preview-only source의 ID 충돌은 dict 병합 전에 거절한다. 새 producer credential은 기존 phone/sighting/preview-signing/pairing-sync/Fleet/robot/site-user credential과 재사용하지 않는다. Vision source ID와 호환되도록 모든 source_id는 `[A-Za-z0-9_-]{1,32}`로 제한한다. 이 제한은 앞선 일반 workcell/arm ID 길이와 별개다. 16KiB ingest 한도는 Content-Length뿐 아니라 실제 수신 bytes에 적용한다.

Board ID와 token_env는 최대128자, topic과 device selector는 최대256자다. 관측 manifest의 arm_id는 Fleet 전체에서 유일하며 카메라의 대응은 같은 workcell 안에서 확인한다.

Bridge와 Fleet는 상주하되 ROS topic을 읽는 역할만 한다. 초기 idle reader의 지속 실행은 별도의 명시적 persistent torque-OFF read-only 모드로 제공한다. 기존 whitelist·sample freshness·model/fault·독점 검사와 cleanup을 유지하며 torque ON·fault·소유권 충돌 때 종료하고 자동 재진입하지 않는다. 300초 observer를 systemd 반복 재시작으로 연장하지 않는다. Accepted owner로의 handoff는 reader 중지→프로세스/FD 종료와 bus 해제 확인→별도 승인된 owner 시작 순서다. Active owner feedback을 사용할 때는 producer·units·source binding을 명시적으로 전환한다. 자동 source 전환이나 두 serial opener의 공존은 범위 밖이다.

브라우저는 기존 Fleet client와 동일 origin을 사용한다. 각 팔·카메라는 독립 만료하며 연결 중단 시 마지막 값을 지운다. 로그아웃과 credential 교체는 표시·비동기 응답을 무효화한다. 관측 cache는 World pose, Task 성공, motion admission 입력으로 사용하지 않는다. CORE와 OMX owner의 기존 실행·정지 권한은 유지한다.

### Consequences

Native service와 Fleet/Vision release/configuration까지 배포해야 개발 PC 없이 관측이 유지된다. source/host/browser 시험, 설치된 artifact, 실제 producer→Fleet/Vision→ROSY 화면, 보정·동작·현장 수용을 따로 기록한다. 이 결정의 채택이나 구현만으로 실물 움직임 또는 딸기 파지를 완료했다고 주장하지 않는다.
