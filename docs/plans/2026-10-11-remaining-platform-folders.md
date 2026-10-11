# 남은 플랫폼 폴더 정리 실행 계획

기준 local main `ea6d4c0a2`, 브랜치 `refactor/remaining-platform-folders`, D-637. 이전 D-630 단계는 끝난 이력이며 이 계획은 남아 있던 실제 source holder를 처리한다. 사용자가 승인한 순서인 실제 이동·소비자 수정 → 검증·커밋·local main 머지 → 결과 설명 갱신을 따른다. ADR·실행 계획은 구현 전에 기록한다.

| 단계 | 할 일 | 완료 근거 |
|---|---|---|
| 1. 재고·계약 대조 | 현재 85개 manifest root, 실제 파일, D-425/D-429/D-625/D-630과 보류 이유 대조 | actual source와 cache·tool state 구분, caller/config/export/test 목록 |
| 2. Decision | 실제 10파일을 `operations/decision/src/rosy/decision`으로 이동; D-429의 namespace 개명과 호출자 일괄 변경 | source import·제안/도구 transaction·금지 경계·installed 동일 객체; `fleet.ai` shim 없음 |
| 3. Console | 실제 66파일을 `operations/ui/console`로 이동 | 동일 URL/allowlist/CSP; wheel·sdist 설치 자산 목록과 HTTP 서빙 검사 |
| 4. 학습 | dataset57·classes3·review docs를 curation, model20와 store를 registry, trainer27을 기존 training root, replay3을 evaluation에 배치 | 서명 source closure·service·intake/store·notebook·시험 lookup 함께 수정; 기존214파일을 한 번씩 처리 |
| 5. 지원·시험 | 운영 CLI/SSH helper를 tools/perception, JPEG relay를 Gazebo, review smoke를 검토 앱으로 이동; shared fixture의 99시험을 test/learning/perception에 배치 | 기존 설치 destination·CLI 동작·private fixture·브라우저 harness 유지, 과거 검증 기록 보존 |
| 6. 소스 착지 | 필요한 독립 리뷰 후 committed SHA remote 회귀와 known_failures, harness lint·Safety·diff 검사 | 새 실패 0; unit별 commit과 `tools/land.py` local main fast-forward |
| 7. 설명·계획 닫기 | 새 구조·경계·테스트 배치·유지 항목·후속 계획과 실제 착지 SHA 기록 | module AGENTS·root 안내·현행 실행 계획·검증 기록 일치; 문서 별도 commit·검사·착지 |

Fleet setup·source holder helper·manifest·root reference는 주 세션이 통합한다. Decision 구현·호출자와 학습/지원 도구는 독립 소유 경로에서 작업하며 공동 파일은 순차로 조정한다. 새 API, 장치 명령, namespace 호환 framework, action-conditioned World model이나 빈 미래 holder는 추가하지 않는다.

`tools/perception/rosy_ml`은 여러 learning owner를 조합하는 운영 진입점이다. trainer는 training 계약만, curation은 기록·정답·dataset provenance만, registry는 수용·revision·승격·배포 도구만, evaluation은 기존 replay 평가만 소유한다. 실행이나 모델 활성화 증거는 경로 정리와 별개다. 99파일의 기존 시험 suite는 shared private-delivery fixture·브라우저 harness를 유지한 채 `test/learning/perception`에 배치하며 각 소비자 lookup과 검증 범위를 명시한다.

잔여 Gazebo launch/script manifest의 `deferred`는 하나의 `gz_sim` 배포·share·source resource 안에서 구분한 concern이다. 단순 이름 변경으로 별도 runtime/device package를 만들지 않는다. 실제 owner에 맞는 기존 launch/script는 유지하고 잘못 놓인 설치 relay만 그 owner로 옮긴다. 모델 artifact·data·private config·동료 `.omc` 상태도 제품 이동 대상으로 집계하지 않는다.

## 검증·진행 기록

각 implementation commit은 독립 source 리뷰 후 원격 시험에 보낸다. 테스트 수·성공/실패·known_failures·반영 SHA는 실제 terminal 결과로 채운다. 자동 selection이 FULL로 확대되면 CI FULL이 남는다는 점을 기록한다. push·배포·ROS/ARM64·실물·현장 수용을 문서만으로 완료 처리하지 않는다.
