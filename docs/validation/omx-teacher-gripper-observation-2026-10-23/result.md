# 고정 teacher 수집의 그리퍼 유지 판정 HOLD

2026-10-23. source `a5661aa3f58a31f5369f84a1177a06ba17043473`, native run
`a5661aa3f58a31f5369f84a1177a06ba17043473-ded681887bcc`.

새 고정 cohort `CT20261023a566`는 앞선 9개 완료 뒤 네 번째 배치의 첫 시도에서
EXITED1/HOLD했다. 이번 시도는 실패1개이며 나머지15개 슬롯은 실행하지 않았다.
원본 녹화는1023프레임·capture complete·issues 없음이지만 task_outcome은 failure다.
배치 실패·성공 에피소드·미실행 슬롯을 섞거나 누락 슬롯을 대체하지 않는다.
학습·정책 평가·admission은 실행하지 않았다.

## 원본과 정리

- 오류: `GripperReadbackError: gripper readback does not prove the requested object is held`.
- watchdog 관측 null. 최종 owner는 ready이고 joint_age_ms는6이지만 실패 표본을 대신하지 않는다.
- canonical cleanup_verified=true, process-cleanup remaining_groups=[], verified_absent=true.
  종료 helper는 failed/ExecMainStatus1/ControlGroup 빈 문자열이었다.
- 원본 archive11,676,595bytes의 실제 해시와 receipt가 일치한다.
  아카이브·추출 매핑을 통해 전체1,091개 파일의 바이트를 비교했다.
  fetch receipt의 snapshot 표기는 OBSERVATION_NOT_ATOMIC이며 원자 스냅샷으로 주장하지 않는다.

| 보존 근거 | SHA256 |
|---|---|
| 고정 cohort progress | sha256:84d9d0f546f42a542c8c3cb6ee51b6d6eb3799201693c3425c9df20f42bbcead |
| native archive | sha256:202f616b64f626459a07fe8a752768f2e3683ce02901decdc361df67fc2f8941 |
| extraction map | sha256:8b3f7fc3470f3a1de8bbcbc21faecd2c146c0a6e21a1a961680c57f713108ecc |
| source inventory | sha256:dd0b31e8250c0bd626be4802ad2196a5f59c44a2d670b1d27c76809cd13f673f |
| dependency inventory | sha256:b8e5c71b6c03419dcb29e8bde930b1dd8f24028abad3debada61f0eafdce0b8d |

source와 dependency inventory는 수집 전에 고정한 적격 입력과 일치한다.
기존 db4 수집본의 HOLD와 원본 해시도 변경하지 않았다. 회수 원본은 소유 세션의
외부 scratch `current-teacher-cohort-a566/batch-04-train` 아래에 보존했다.

## 관측으로 확인한 범위

grasp의 held receipt와 SIM AID attach가 성공한 뒤 transfer에서109개의 hold command를
기록했다. 마지막 command는303번째이고 그리퍼 목표는0.38042608841813563rad이다.
정확한 오류 경로는 먼저 freshness를 통과한 뒤 width-matched contact predicate에서
거부됐음을 뜻한다. 실제 힘·독립 물체 센서의 판정이 아니므로 물체 낙하를 확정하지 않는다.
SIM 부착 확인도 held 검증을 대체하지 않는다.

이 recipe/profile의 close는0.38042608841813563rad, contact는0.40689174134023rad이며
판정 구간은[0.3936589148791828,0.42189174134023]rad이다. 마지막 성공 표본의 q는
약0.4035344422rad로 구간 안에 있다. **최종** q≈0.39269rad는 하한보다 약0.000969rad
작지만 실패 순간의 표본이 아니다. 어느 경계를 위반했는지와 그 물리 원인은 미확인이다.

기존 `grip()`은 verifier가 예외를 던지면 반환 전에 관측을 잃는다. 같은 한계가
[10월17일 기록](../omx-native-held-proof-2026-10-17/result.md)에 명시돼 있다.
따라서 최종 상태나 별도 observer의 가까운 시각으로 실패 순간을 재구성하지 않는다.
이전 `joint_state_stale` HOLD가 이번에 재현됐다고도 주장하지 않는다.

## 진단 보완과 검증 경계

실패 시 기존에 읽은 관측·전체 관절 위치·각도·판정 범위·시각·phase·선행 command만
보존하는 보완을 준비했다. 새 joint/object/clock 읽기나 명령은 추가하지 않으며
기존 예외·판정 기준·bounded squeeze·정리 경로는 유지한다.
테스트 전용 revision `90b4bb3d0e`의 원격 실제 결과는 FFF..FFFF로7실패·2통과였고,
누락된 실패 근거와 helper를 재현했다. malformed/nonfinite 진단 시험은 실제 계약이
거부하는 NaN observation을 만들지 않고, 유효 관측과 비정상 진단 scalar를 구분한다.
수정 코드의 원격 결과와 통합 여부는 별도 검증 기록으로 남긴다.

진단 보완의 단위 시험은 grasp 물리 원인 해결이나 새 native 실행 성공의 증거가 아니다.
이 cohort는 HOLD로 보존하며 교사 데이터·학습·독립 정책 평가를 완료했다고 표시하지 않는다.
CE: 미해결 — 실패 순간 근거 누락과 물리 원인은 구분하며 원인 해결 교훈은 아직 쓰지 않는다.
