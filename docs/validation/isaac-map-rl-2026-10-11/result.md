# Isaac map RL 결과 — 진행 중

목표와 문제 해결 과정은 [진행 기록](process.md)을 따른다. 기존 CORE·Drive의 한 대 CPU residual RL 진단(D-638)이다. 현재 학습과 전체 맵 완주는 아직 통과하지 않았다.

| 증거 | 현재 판정 |
|---|---|
| 최신 main 병합 | `f821d27dc5` 로컬 착지, 449 passed / 1 skipped / 0 NEW; push 없음 |
| 계약·원격 회귀 | 241 passed / 1 skipped / 0 NEW (`51d77f23fb`); Drive 연결 50 passed / 8 subtests passed (`6bc91f8e36`) |
| 지도 lineage | 원본 STL SHA-256 고정, training-curved graph와 기존 geometry generator 사용 |
| native Isaac import | 지도·네 벽·차선·한 Pinky 로딩까지 실행 |
| 최초 물리 정지 | 실패, 실제 yaw rate 0.06961rad/s 마지막 관측; 학습/reset 시작 거부 |
| Q-learning / 고정 정책 완주 | 아직 미검증 |
| D-606 Isaac Lab / 두 대 Fleet·신호 / 실물 | HOLD, 이 진단으로 대체하지 않음 |

실행 결과는 종료 코드·물리 readback·cleanup까지 확인한 뒤 이 파일에 추가한다.
