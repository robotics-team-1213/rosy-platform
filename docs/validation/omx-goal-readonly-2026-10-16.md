# OMX 목표 레지스터 변화의 독립 읽기 전용 관찰

2026-10-16, D-770 후속. [native passive read의 보존 검사 실패](omx-measured-status-2026-10-16/result.md)를
수정된 driver 없이 별도 관찰했다. 이전 실패 기록과 gate는 유지한다.

실제 follower를 기존 by-id 식별자로 열고, committed register_probe의 kernel 독점 소유와
단일 owner 검사를 재사용했다. 한 handle에서 PING/READ(0,147)만 허용하는 writer로
30회 snapshot을 기록했다. 각 snapshot 시작/종료 시각을 보존했고 전체 deadline은 8초,
각 회 사이 대기는 100ms였다. torque/error·mode·model 불일치에서는 중단하도록 했다.
실제 실행은 예외 없이 30회를 완료했다. 상태 변경 명령·물리 조작·native 재실행은 없었다.

여섯 모터의 torque0/error0 및 기존 mode를 유지했다. ID14의 목표와 현재 위치가 함께
3195↔3196으로 바뀌는 전이가 인접 snapshot 사이에 11회 관측됐다. SDK write 경계의
기록은 모두 허용된 PING/READ였다. 원본 snapshot과 프로그램/reader/로그 hash를 보존했다.

이는 native driver가 실행되지 않은 읽기 전용 통신에서도 해당 변화가 나타남을 보여준다.
모터 firmware 내부 원인, 이전 SRAM mapping의 영향, 부하·정지·물리 안전을 확정하는
시험은 아니다. native 실행의 전후 goal 보존 검사를 통과로 바꾸거나 허용 오차를
늘리지 않는다. 목표 쓰기 없이 값이 바뀌는 실제 관찰을 첫 활성화의 초기 목표 보존과
readback 설계에 반영한다. 실제 구동·시연·모방학습 데이터 수집 완료는 여전히 아니다.

원본은 Fleet private `~/rosy-test/omx-goal-readonly-20261016/`의 `observe.py`,
`register_probe.py`, `samples.jsonl`, `receipt.json`이다. reader hash는 앞선 고정
artifact와 일치시켰고 full hash는 private receipt가 소유한다. 이 진단에서 운영 prefix나
service를 바꾸지 않았다. 실제 자동 시연은 0회다.
