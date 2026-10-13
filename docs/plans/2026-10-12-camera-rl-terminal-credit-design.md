# 카메라 차선 상실의 종료 벌점 연결

## 문제와 목표

기존 native 학습 기록에서 camera_lane_lost로 끝난 18회 모두 reward 약 -10을 만들었지만, learn_transition의 현재 state=None 검사로 정책 갱신을 건너뛰었다. invalid 관측을 학습 state로 승인하지 않는 계약은 유지하면서 이미 실행된 행동의 실패 결과를 누락하지 않는다.

## 선택

최소 변경은 해당 episode에서 CORE를 통해 실행한 마지막 유효 state/action을 보관하고, 명시적 camera_lane_lost 종료에서만 그 행동에 terminal reward를 부여하는 것이다. 다음 state는 None이고 bootstrap은 0이다. 카메라 관측을 복원하거나 기억된 명령을 다시 실행하지 않는다.

다른 선택은 카메라 프레임 단위 action 유지·보상 누적·시간 기반 discount까지 한 번에 재구성하는 것이다. 이는 의사결정 주기를 바꾸므로 별도 원격 및 native 비교가 필요하다. 이번 수정은 확정된 종료 벌점 누락에 한정한다.

## 경계와 증거

- last_applied와 source frame은 episode마다 초기화한다. 유효 state와 실제 CORE 명령 처리가 확인된 뒤에만 갱신한다.
- send의 바퀴 적용 성공 뒤 receipt가 후보와 일치하고 최종 명령이 nonzero이며 cycle warning·halted가 없을 때만 보관한다. CORE 정상 반환만으로 실행을 추정하지 않는다.
- ZERO 구간은 직전 기록을 유지하지만, held-path 등 비학습 nonzero 명령이 실제 전달되면 기록을 비운다. 다른 제어기의 이동 결과를 이전 RL 행동에 돌리지 않는다.
- 현재 관측이 없고 명시적 camera_lane_lost terminated인 경우만 마지막 실행 행동에 실패 벌점을 준다. 유효 행동이 없거나 nonterminal/truncation/다른 실패이면 기존 무효 관측 거절을 유지한다.
- 종료의 세부 원인이 camera_target_unavailable인 경우만 연결한다. 카메라 stale·추론 오류·scan 오류와 원인 누락은 기존 실패 종료/정지를 유지하면서 조향 credit에서 제외한다.
- 유효한 다음 state가 있는 기존 전이는 변경하지 않는다. 동일 종료를 반복 학습하지 않도록 기존 episode break를 유지한다.
- camera freshness, body sweep, CORE 최종 명령, 실제 정지·cleanup, 평가 수용 기준은 변경하지 않는다.
- trace에 종료 벌점을 받은 행동의 frame을 남긴다. 원격 RED/GREEN, 무효 상태·다른 종료 회귀, native terminal credit와 정책 update readback을 확인한다.

## 남은 범위

이 수정은 완주나 RL 성능 향상을 보장하지 않는다. physics tick 단위 학습·discount의 시간 의미, 카메라 목표 기하, 한 대 완주, 병렬 학습, 두 대 Gazebo Fleet·교통 규칙 수용은 계속 별도 검증한다.

## 재현

원격 회귀의 camera_loss 선택으로 종료 벌점 누락을 재현했다. 새 positive 사례는 invalid_camera_observation을 반환하여 실패했고, 부정 사례 5개는 통과했다. known_failures 비교는 NEW 1이며 기존 실패로 분류하지 않았다. 앞선 terminal 선택은 positive 함수 이름을 포함하지 못했으므로 RED 증거에서 제외했다.
