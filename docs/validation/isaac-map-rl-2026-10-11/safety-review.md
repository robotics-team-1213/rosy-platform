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

추가 네 방향·실제 녹화 b6a8d0d2e8: 별도 리뷰어가 saved policy 동일 bytes의 bounded read/restore/copy, 평가 중 정책 불변, 기존 CORE/물리 reset 경로, native SDK5.1 Fabric renderer receipt 형식을 확인했다. 물리 cleanup 실패에도 encoder close를 시도하고 pipe close 오류에도 child wait/timeout kill을 수행하도록 교정했다. 실패는 nonzero로 전달된다. 최신 HEAD 재확인 뒤 소스 범위 APPROVE. 실제 영상·원격 회귀·방향별 주행은 리뷰어가 직접 실행한 증거가 아니며 실행자가 별도로 검증한다.
경로 이동 commit 764b591ed6: 기존 tools/sim 소유로 map_task/run_map_rl/native_recording을 옮긴 변경을 독립 재검토했다. 저장소 root 계산·SDK helper 연결·CORE 최종 권한·stop/cleanup·고정 정책·맵 hash를 유지하며 누락/새 blocker 없음으로 소스 Safety-Review APPROVE. 리뷰어는 pytest/이동 뒤 runtime을 실행하지 않았으며 R8/R9 증거는 원래 SHA에 귀속한다. primary의 원격 Isaac/architecture/release/harness 재시험 exit0/NEW0은 별도 증거다.
