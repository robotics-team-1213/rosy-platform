# 책임 분리 착수 시 소유자 확인

확인 기준: `51ad9b355f` 소스. D-656/후속 계획 Task 0의 읽기 결과다. 설치·원격 시험·배포·실제 현장 결과는 이 표만으로 확인되지 않는다.

| 경계 | 입력 생산자 → 실제 소비자 | 쓰기 및 종료 소유자 | 설치·실행 위치 |
|---|---|---|---|
| 모델 원장 도구 | Decision의 `ModelToolCall` → `MissionFeedbackToolDispatcher` → 주입된 Mission/Progress/Proposal 서비스 | Fleet 서비스의 기존 원장 트랜잭션. 모델은 도구 허용 목록 안에서 조회·후보만 제출 | 현재 Decision source holder가 Fleet wheel/sdist에 포함. 현장 Fleet PC |
| 모델 런 | `MissionModelTurnScheduler` → `MissionModelTurnWorker` → 주입된 provider/dispatcher | Fleet 모델 turn journal/lease. 런 종료는 worker, Mission 종료와 별개 | Fleet. 외부 모델 호출 위치와 학습 PC 배포는 별도 |
| Mission 진행 | `MissionStore.progress_snapshot_data` → `MissionProgressService.snapshot/model_context` → API/모델 도구 | store가 스냅샷의 일관성을 소유. projection은 쓰기 없음 | Fleet. 순수 계산만 execution으로 추출 예정 |
| 목표 근거 | 독립 camera evaluator → `GoalEvidenceService`/`MissionService` → `verify_goal` | Fleet가 provenance·현재 attempt를 검증하고 기존 원장에 결과 기록. 모델 요약은 목표 성공 근거가 아님 | 현재 Fleet. 순수 검증만 execution으로 추출 예정 |
| Pinky 차선 사건 | CORE `line_follow.stuck`/관측 → `LineStuckBoard.observe` → Console/`StuckResolverLoop` | board의 열림/해소 전이가 기존 `LineStuckAnswerLog`에 기록. 답변 수락과 물리적 해소는 별개 | CORE는 로봇, board/resolver/log는 Fleet PC |
| 공통 필요성 | CORE snapshot → 순수 Situation assessment → Fleet shadow/Console context | assessment 쓰기 없음. shadow 판단이 사건 종료나 장치 명령을 대신하지 않음 | Situation의 순수 세 파일이 Fleet wheel/sdist/source image에 포함 |
| 현장 명령 | Fleet claim/admission/stop-generation → CORE 또는 OMX readback | Fleet가 발행 직전 권한을 재검증. 최종 장치 writer는 CORE/OMX | Fleet PC 및 로봇/셀 장치 |
| 독립 평가 | 실제 관측·사람 검토 → curation/replay → 수용 receipt | 모델 답변과 별도 정답 필요. provider가 자기 결과를 승격하지 않음 | 학습·평가 Model PC. 현장 정답·threshold receipt 미확인 |

| 사례 | 현재 owner/근거 | 후속 확인 |
|---|---|---|
| Pinky 차선 정지·재관측 | CORE가 정지 사실, Fleet가 현재 사건/답변, 독립 관측이 해소 확인 | 사용자가 첫 현장 수용 대상으로 선택. 현장 readback 필요 |
| 정상 비개입 | CORE normal snapshot과 순수 `DO_NOT_INTERVENE` | 새 명령·알림 0, 정상 분모에 포함 |
| 관측 부족 | Situation `ABSTAIN`, Fleet 사람 검토 | 정상과 구분하며 정해진 기한 이후 미대응도 평가 |
| Arm 단일 셀 | OMX action readback, 독립 camera goal predicate, Fleet Mission/Cell 원장 | 다음 도메인. 장치 완료만으로 목표 성공 처리 금지 |
| 다중 로봇 교통·교착 | Fleet roster/map trust와 현장 중재, 각 CORE 최종 writer | 지도·관측 신선도와 개별 결과 필요 |
| 문 앞 정지 | 공통 판단의 입력 형식만 재사용 가능 | 문 센서·capability·독립 정답 미확인. adapter 활성화하지 않음 |

팀원이 사건을 함께 보고 인수하는 무료 알림을 요청했다. 기본 구현 대상은 Discord 채널 웹훅, 인수·결과의 원장은 인증된 Console과 기존 사건 DB다. 실제 채널 설정 및 수신·인수 readback은 아직 없다. 근거: [Discord 웹훅](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks), [무료 Telegram Bot Platform](https://core.telegram.org/bots), [Slack 무료 이력 제한](https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack).
