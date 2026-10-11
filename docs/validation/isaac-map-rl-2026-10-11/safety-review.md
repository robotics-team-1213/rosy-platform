# D-638 simulation owner 독립 소스 검토

검토자: 별도 `rl_safety_review` agent, 읽기 전용. 기준 main `f821d27dc5`, 초기 검토 HEAD `e8dba4892`.

- POLICY 0.1초 만료가 NAV 0.5초 후보 수명에 묻히는 문제: `SimulationOwner.select_output`의 최종 검사로 수정.
- 음수/bool 시각의 예외가 기존 후보를 남기는 문제: 비음수·유한 수치 검사와 0/HOLD 처리로 수정.
- runner의 후보·관측 시각은 monotonic, task elapsed는 physics time으로 구분됨.
- 모든 reset 전에 CORE 슬롯 삭제와 실제 zero dwell을 요구함.
- 최종 출력은 owner를 통해 기존 CORE `cmd_vel_cycle`과 단일 SDK wheel action callback으로 이어짐. 실물 API·ROS publisher·Fleet 연결 없음.
- 학습 0회에도 fallback 완주가 성공으로 기록될 수 있는 문제: updates>0, 비영 Q, 실제 학습 상태의 주행 후보 적용을 요구하도록 수정.
- cleanup과 SDK close 실패가 결과에서 빠지는 문제: finally 결과 재기록으로 수정.

수정 확인 뒤 소스 범위 수용 가능으로 판단했다. 실행·원격 테스트·실제 완주 수용은 이 소스 검토에 포함하지 않았다. 이후 기존 Drive PathFollower 연결과 물리 정지 진단 변경의 실행 증거는 진행 기록을 따른다.

추가 검토 `72a4c5aa2`: 기존 PathFollower 연결, 1/240초 물리 간격, reset 후 실제 gains 기록, 0.5초 대기 유지와 고정 경로 창을 확인했다. 매 진행점마다 끝점이 바뀌어 alignment 이력이 초기화되던 문제는 동일 suffix를 유지하도록 수정했다. 새로운 중요 소스 안전 결함을 발견하지 않았으며 소스 범위 수용 가능으로 판정했다. 이전 R5 snapshot과 최신 R6 실행 결과는 별도 증거다. 리뷰어는 해당 런타임을 직접 검증하지 않았다.

추가 종료 수리 `e0e5b38d78`: 리뷰어가 설치 SDK의 stage-close와 GUI 메뉴의 event/action 제거 경로를 확인했다. 공통 close_sdk를 모든 caller의 기존 zero/정지 뒤 finally에 연결했다. disable 확인 실패에도 SDK close를 시도하고 예외는 비정상 종료로 전달한다. 소스 검토는 수용 가능이다. R7 raw 로그·종료 readback은 실행자가 별도로 확인했다.
