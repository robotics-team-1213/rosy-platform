# D-672: Pinky 판단과 후보 토론의 연결 및 호스트 실행 책임

- Status: Accepted
- Date: 2026-10-12
- Related: D-640, D-652, D-660

## Context

문·암 fixture만으로는 첫 수용 대상인 Pinky의 차선 정지 판단을 검증하지 못한다. CLI 번역기와 프로세스 격리를 같은 판단 모듈에 넣으면 설치 책임과 의사결정 책임이 섞인다.

## Decision

Fleet의 기존 `LineStuckBoard.intervention_assessment` 결과를 `run_line_judgment`에 전달한다. 정상 상태는 모델 호출 없이 `NOT_NEEDED`, 기권·관측 부족·만료·다른 사건은 `HOLD`다. `INTERVENE`이며 현재 CORE 상태 근거가 유지된 사건만 기존 원장과 Decision supervisor에 연결한다. 입력은 `line_follow` 도메인, 원래 관측 시각·상태 revision·근거 ID와 `blocked` 사실뿐이다. 차선 상실의 구체 원인이나 영상 인식 결과를 새로 추정하지 않는다. 처리 방향은 `reobserve`와 `human`이며 항상 `action_admissible=False`다.

현재 사건·전체 요청·정책 revision·유효 시간을 매 호출과 최종 반환에서 재확인한다. 정상 재관측으로 관측 시각을 갱신하거나 다른 상태 revision의 답을 재사용하지 않는다. 공개 HTTP/worker 자동 호출과 CORE 명령 경로는 추가하지 않는다.

Decision은 후보·CLI 번역을 소유한다. Fleet은 판단 입력과 기존 DB 원장을 소유한다. `deploy/site/deliberation_sandbox.py`는 Linux 호스트 실행과 고정 실행 파일 snapshot을 소유한다. 전용 네트워크·PID namespace, 읽기 전용 runtime, 빈 환경, 제한 cgroup 및 해당 scope 전체 종료를 요구한다. 현재 버전은 offline-only다. 공급자 인증·네트워크 허용과 실제 모델 선택은 별도 수용 후에만 활성화한다.

Discord 구현·설정·발송은 담당 세션의 책임이다. 사람 정답과 정확도·지연 한계는 팀의 검수 책임이다. 구현 시험과 모델 합의를 현장 정답·물리 성공으로 기록하지 않는다.

## Verification

Pinky 정지·정상·관측 부족·stale·사건/세대/정책 변경, durable 재호출 억제와 프로세스 출력 초과·취소·자식 종료를 원격 시험한다. 실제 호스트 격리·제공자 실행·독립 평가·현장 수용은 각각 별도 증거다.
