# ARM transfer 종료 후 작업 판정·검수 자료 연결

## 확인한 범위

기존 simulation 프로필 observer 입력을 통해 Action 성공과 task 성공·목표 미달·미확인을 구분한다. 판정과 원본 관측은 기존 Fleet 이벤트 원장에 보존하고 검수용 JSON으로 내보낸다. 실제 완료·claim 해제는 기존 `confirm_physical`만 수행한다.

구현·문서 검토 revision: `e7093c177af8315faad9a27d342879e23c0b5b77`. 기준 revision: `c2e21981ecee89285647ce2a392aaac76eeee6f3`.

## 원격 시험 증거

로그는 개발 PC 시스템 임시 폴더 아래의 작업별 디렉터리에 보존했다. 실제 호스트 주소·계정·token은 이 기록에 복사하지 않는다.

| revision | 시험 | 결과 | 로그 디렉터리 |
|---|---|---|---|
| `f8e3e59f7b` | 새 순수 task 판정 | 12 failed: 아직 없는 모듈 | `rosy-transfer-outcome-red` |
| `300ec49adc` | 순수 판정 + 기존 physical evidence | 40 passed | `rosy-transfer-outcome-a1` |
| `068d2f5abb` | observer 기록·export 요구사항 | 5 failed, 2 passed | `rosy-transfer-recording-red` |
| `d9f19c65b5` | 관측 ingress·기존 closure 통합 | 6 failed, 108 passed: JSON context를 Python strict tuple로 잘못 복원 | `rosy-transfer-recording-green` |
| `6be67a9176` | JSON 계약 복원 뒤 통합 | 114 passed | `rosy-transfer-recording-green2` |
| `ac8ecb0ca5` | PRE_DISPATCH ID·sequence 재사용 반례 | 2 failed: 잘못된 판정 자료가 보존됨 | `rosy-transfer-novelty-red` |
| `81988c1eb0` | 공유 post-action 계보 검사 뒤 통합 | 116 passed, 0 skipped | `rosy-transfer-novelty-green` |

116개 통합 시험은 새 두 suite와 기존 physical-transfer evidence/observer API/closure/outcomes/stops suite다. 공식 `remote_pytest.py`만 사용했다. GREEN 로그를 `test/known_failures.py`로 비교했으며 NEW 0, known 0, flaky 0이다.

`e7093c177a`의 affected 선택은 Fleet 전체와 역의존·guard 묶음 두 invocation이다. 두 실행 모두 공식 runner exit 0이며 각 로그의 known NEW 0, known 0, flaky 0이다.

| 로그 | 범위 | 결과 |
|---|---|---|
| `rosy-transfer-affected/run-1.txt` | 역의존·guard 선택 | 4,607 passed, 190 skipped, 5 subtests passed |
| `rosy-transfer-affected/run-2.txt` | Fleet 전체 | 7,052 passed, 389 skipped |

합계 11,659 passed, 579 skipped다. 건너뛴 항목은 확인한 것으로 계산하지 않는다. browser opt-in·ROS/장치·모델 품질 수용을 이 합계로 주장하지 않는다. 별도 Python typecheck 설정을 추가하지 않았으며 harness lint는 0 errors, size-range는 구현 커밋별 검사를 통과했다.

## 독립 검토

별도 읽기 전용 계약 검토자가 실제 observer → 판정 → 원장 → 완료/claim 해제 → export 경로를 추적했다. 최초 검토에서 동작 전 관측 ID·sequence 재사용을 판정 기록이 먼저 받아들이는 P2를 발견했다. 원격 RED로 재현한 뒤 기존 완료 검사와 같은 `validate_post_action_order`를 재사용하도록 수정했다. `e7093c177a` 재검토에서 남은 중요 발견은 없었다.

추가 reuse·quality·efficiency·test-value 검토에서 필요한 변경을 찾지 못했다. helper docstring 두 개를 삭제하자는 소규모 제안은 모듈 간 검증 계약의 역할을 설명하는 문장으로 유지했다. 기존 proof test를 약화하거나 삭제하지 않았다.

## 실행·데이터의 한계

- 관측 결과는 `observation_assessment_only`다. 완료 트랜잭션이 거절된 상태에서 그 기록만으로 작업 완료·자원 해제·재시도를 허용하지 않는다.
- 실패·미확인 관측은 기존 HTTP 완료 계약상 409를 유지하면서 검수용 기록으로 보존된다. 잘못된 출처·attempt·시각·원본 계보는 판정 기록을 만들지 않는다.
- 내보내기는 `unreviewed_metadata_only`이며 RGB·실제 적용 행동이 없는 자료를 ACT/VLA 행동 시연으로 수용하지 않는다. DB 전체 재작성에 대한 인증 증거도 아니다.
- 목표 미달을 헛잡음·낙하로 추정하지 않는다. 단계별 실제 관측 생산, 다중 attempt 원장 이관, 자동 복구·재파지, 모델 학습·품질 비교는 남아 있다.
- 실물 장치·ROS/Gazebo 과제 성공·ARM64 설치·현장 수용을 이번 시험으로 입증하지 않았다. main 착지·push·운영 활성화를 수행하지 않았다.

CE: 해당 없음 — 새 구현 과정의 결함은 코드·회귀 시험·이 기록에 드러난다. 별도 장치 성질이나 기존 코드에서 복원할 수 없는 해결 교훈을 확인하지 않았다.
