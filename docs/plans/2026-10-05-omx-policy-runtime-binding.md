# OMX 정책 세션과 원본 런타임 결선

기존 SIM 전용 정책 세션을 동일한 ArmCommandOwner와 RosArmCommandRuntime에 연결한다. 별도 드라이버나 명령 발행자를 만들지 않는다. 정책 lease를 Fleet Action 또는 D18 부모 실행 권한으로 바꾸지 않는다.

## 구현 범위

- 동일 owner, action port, steady clock, 단독 learned_policy 구성과 이미 검증된 관측을 확인하고 한 번만 연결한다. 기존 제어 admission이 있으면 교체하지 않는다.
- 관측은 세션을 통해 owner에 한 번 전달한다. watchdog은 정책 lease와 원본 관측을 함께 검증한다. raw runtime/owner 제출은 거부한다.
- SQLite journal에 원본 설치 manifest, 모델·정규화·평가 참조 바이트, controller/config/install binding을 보존한다. 이 파일 snapshot은 resident bytecode 또는 추론에서 실제 사용한 바이트의 증명이 아니다.
- 영속 intent 후 원본 callback sink를 등록하고 마지막 제출 경계를 재검증한다. 제출이 시작된 뒤 실패·불명확 결과에도 sink를 유지해 늦은 원본 goal UUID/terminal을 기록한다.
- I/O 후 권한·설치·stop·후보가 사용한 원본 관측/카메라·lease를 재검증한다. 상실 시 원본 handle을 취소하고 HOLD한다. callback 저장 실패도 같은 경계에서 차단한다.

## 현재 검증과 남은 조건

호스트 관련 시험 585 PASS/4 환경 SKIP, NEW0. 독립 검토에서 callback 유실과 I/O 중 권한 철회·원본 camera 만료 경계를 찾아 수정했다. 최종 독립 판정은 별도 증거를 따른다.

격리 WSL Jazzy의 기존 native ROS 런타임 시험은 6 PASS다. 새 정책 세션 결선 probe는 mounted 파일/SQLite 확인 중 관측 유효시간을 넘겨 거부됐다. 원래 50ms fixture와 별도 명시적 500ms synthetic fixture 모두 성공 실행으로 인정하지 않는다. 실제 설치 timing을 늘리거나 gate를 해제하지 않는다. 원인별 시간을 측정하고 실제 설치 budget 안에서 결선을 검증해야 한다.

SOURCE/HOST와 ROS transport 결과를 구분한다. 실제 inference, vendor task, 장치, 물리 정지, Fleet 부모→D18→Episode→Fleet 결과는 이번 단계에서 수용하지 않는다. 전체 목표는 계속 진행 중이며 실주행은 모든 시도 합계 0.20m 제한을 유지한다.
