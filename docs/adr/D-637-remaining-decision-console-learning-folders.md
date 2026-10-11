# D-637 남은 Decision·Console·학습 소스 폴더의 실행

**Status:** Accepted (2026-10-11, 사용자의 남은 폴더 정리·설명 수정·계획 대조 요청). 소스와 local main 착지 범위이며 push·배포·실물 활성화는 별도다.

## Context

D-630의 실제 이동을 local main에 반영했지만 Fleet의 AI와 Console, 학습의 dataset/model/trainer가 이전 구현 holder에 남아 있었다. D-625의 의미 구조와 현재 소비자를 대조해 실제 코드가 있는 단위를 추가로 이동한다. 도구 상태·미확인 자료를 제품 소스로 보거나 미래 모델 폴더를 미리 만들지 않는다.

## Decision

| 기존 소스 | 실행할 물리 책임 |
|---|---|
| `operations/fleet/fleet/ai` | `operations/decision/src/rosy/decision` |
| `operations/fleet/fleet/server/web` | `operations/ui/console` |
| `learning/training/perception/dataset`, `classes`, review 안내 | `learning/curation/perception`의 실제 데이터 준비·classes·docs |
| perception `model`, `store.py` | `learning/registry/perception`의 모델 수용·승격·store |
| perception `rosy_ml.py`, `operator_ssh.py` | `tools/perception`의 여러 learning owner를 조합하는 운영 CLI |
| perception `training` | 기존 `learning/training/perception`으로 불필요한 중복 단계 제거 |
| perception `road_replay*.py` | `learning/evaluation/perception`의 실제 offline replay 평가 |
| perception `test`의 99파일 | `test/learning/perception`의 shared fixture와 기존 workflow 검증 suite |
| `tools/review_app_smoke.py` | 데이터 검토 앱의 `learning/curation/perception/tools` |
| `tools/sim_jpeg_relay.py` | `integrations/simulation/gazebo/scripts` |
| 과거 WSL 복사·재시작 스크립트 6개 | `docs/reference/legacy-tools/wsl`의 고정 참조 자료 |

관련 학습 시험은 실제 curation/registry/training/evaluation 소비자에 따라 lookup을 갱신한다. 기존 suite는 하나의 private-delivery autouse fixture와 브라우저 harness를 공유하므로 repository의 명시적인 learning workflow 시험 owner에 한 번만 배치한다. fixture를 네 번 복제하거나 시험 framework를 만들지 않으며 suite의 실제 모듈별 검증 범위를 안내에 기록한다. 새 학습·추론·예측 기능은 추가하지 않는다.

D-429 §5의 예외를 그대로 실행한다. Decision만 `fleet.ai`에서 `rosy.decision`으로 개명하며 호출자와 시험을 같은 소스 단위에서 바꾸고 옛 이름 shim을 만들지 않는다. 순환 의존 분리 권고를 이번 폴더 이동으로 확대하지 않는다. 기존 Fleet 공유 SQLite transaction, 제안 저장·stop/fence·세대·watermark·closed model tool catalog와 실행 금지 경계를 유지한다. 실제 Decision 코드는 기존 Fleet distribution 안에 설치하되 물리 source mapping을 명시한다. 새 별도 서버나 wheel을 만들지 않는다.

Console URL·allowlist·CSP·same-origin 세션과 설치된 `fleet/server/web` resource 경로는 그대로다. source 조회는 새 Console holder를 쓰고 wheel/sdist는 같은 설치 자산을 빠짐없이 포함한다. source mapping과 self-contained sdist는 D-630의 정적 holder mapping 방식을 따른다.

학습의 store layout·고정 revision·READY·서명·intake·shadow/promotion guard는 유지한다. CLI wrapper·서명 source closure·model PC 서비스·Docker·workflow·harness·예제·현행 안내를 새 source와 함께 갱신한다. 기존 등록 checkout의 dirty-source 검사는 새 위치와 이전 위치를 모두 감시하여 이행 중 누락을 막는다. 실제 모델·데이터·설정·overlay·인증·운영 서비스는 이동하거나 활성화하지 않는다.

D-427 `d427_target`은 frozen ownership identity로 유지하고 현재 root·layout·import mapping만 갱신한다. 실제 의미 깊이는 최대 5단계이며 namespace·resource·test 내부 경로는 별개다. AGENTS와 현재 계획은 이동한 실제 위치를 설명하며 Accepted ADR 본문·과거 evidence를 일괄 경로 치환하지 않는다.

## 기존 계약과의 관계

| ADR | 관계 |
|---|---|
| D-427 | 세 part와 frozen ownership identity를 유지하고 실제 source holder와 import mapping만 갱신한다. |
| D-429 | §5의 rosy.decision 개명·shim 금지·같은 transaction 계약을 실행한다. Validation wave 3c의 별도 pyproject와 Fleet 의존성 계획만 기존 Fleet distribution의 명시적 package_dir 설치로 대체한다. 순환 의존 분리는 이번 범위 밖이다. |
| D-430 | Safety namespace 검사 대상을 새 canonical Decision 위치로 옮겨 같은 금지 경계를 검사한다. writer와 Safety API를 확대하지 않는다. |

## Validation and rollback

관련 committed-SHA remote 회귀·known_failures 비교, source import, checkout 밖 wheel과 self-contained sdist 재빌드·동일 Console 자산 목록, source deployment/model-code closure, manifest·의존·문서·Safety 검사를 완료한 단위만 local main에 착지한다. 브라우저 관련 검사는 시험 PC에서만 수행한다. ROS/Jazzy·ARM64·CI FULL·현장 readback·실물 수용은 별도로 기록한다. 실패를 known failure로 추가하거나 시험 assertion을 완화하지 않는다.

실패 단위는 자신의 소스를 역이동하고 자신의 소비자만 역패치한다. main과 동료의 미커밋·ignored tool state는 reset·stash·삭제·이동으로 정리하지 않는다. 스크래치·검증 출력은 X 관리 세션에만 둔다. 기존 map/STL lineage와 CORE 단일 최종 Base writer, OMX Arm owner를 유지한다.
