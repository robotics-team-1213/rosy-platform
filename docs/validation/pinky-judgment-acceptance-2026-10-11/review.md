# Pinky 차선 정지·재관측 독립 수용 준비

사용자 선택: 현장 정답 검수와 Discord 서버/채널 관리는 팀이 수행한다. 이 초기 기록은 미정 프로파일이며 실제 검수/정답/한계/채널/DEVICE/FIELD receipt가 없다. 고정 위험 누락·다른 사건/stale 조치·금지 권한·정상 불필요 명령 0건 조건은 유지하며 관측 부족은 ABSTAIN으로 평가한다. 이 폴더의 초기 파일을 결과처럼 덮어쓰지 않고 팀 검수 뒤 새 dated version에 고정한다.

팀이 준비할 자료는 독립 `labels.json`, 실제 관측/원장에 연결한 `observations.json`, 학습/개발에 쓰인 `training.json` manifest다. 실제 자료는 비공개 X/원격 저장소에 둔다. 기존 Fleet 사건 export와 `incident_feedback.py`는 근거 연결 후보이며 정상 구간 정답이나 자동 승인이 아니다. D-660의 60초 표본 수를 전체 운행 시간으로 치환하지 않는다.

`labels`의 각 행은 `id`, `subject_id`, `case_id`(정상은null 가능), `category`(normal/authorized_wait/blocked/insufficient/conflict/natural_clearance), `expected`(INTERVENE/DO_NOT_INTERVENE/ABSTAIN), `dangerous`(독립 위험 정답), `due_ms`, `session_id`, `location_id`, `recording_sha256`, `start_at`, `end_at`(UTC epoch seconds), `reviewed_by`, `truth_receipt`를 담는다. 서로 다른 정상 구간과 사건의 분모를 고정한다. 정답은 모델 응답에서 복사하지 않는다.

`observations`의 각 행은 같은 `id`, `necessity`, `policy_revision`, `latency_ms`, `elapsed_ms`(고정 평가 구간의 경과), `notification_ms`(미확인null), `command_submitted`, `actual_subject_id`, `actual_case_id`, `command_stale`, `authority_valid`, `action_attempted`, `outcome`(UNKNOWN/PENDING/NATURAL_CLEARANCE/VERIFIED_RESOLVED/VERIFIED_UNRESOLVED), `outcome_receipt`를 실제 자료로 채운다. API 수락을 VERIFIED_RESOLVED로 치환하지 않는다. `training`의 각 행은 session_id/recording_sha256/location_id/start_at/end_at이다. train/eval 세션·recording hash·같은 장소의 겹치는 시간 구간을 거절한다.

팀 검수자는 정답·training의 canonical JSON SHA-256(`judgment_acceptance.digest`)와 정책 revision, 최소 표본/실제 해소 관측 수, 모든 한계를 **실제 평가 전에** 새 profile에 확정한다. CLI는 검수 정보/한계/표본이 미정이면 HOLD(exit2), 금지 건수/확정 한계 위반이면 FAIL(exit1), offline 통과도 PASS_OFFLINE_ONLY(exit0)이며 FIELD를 승인하지 않는다.

```powershell
 # abstain_required_error_rate도 평가 전에 확정한다. 같은 물리 구간을 다른 ID로 복제하지 않는다.
python learning/evaluation/perception/judgment_acceptance.py <reviewed-profile.json> <labels.json> <observations.json> <training.json> --out X:/DevTemp/<registered-session>/judgment-result.json
```

새 팀 Discord 채널 연결은 [팀 채널 절차](../../reference/team-discord-incidents.md)를 따른다. 실제 수신→로그인→담당 인수→원장 readback→현장 결과→종료 통지의 receipt를 함께 준비한다. 모델 토론/CLI 프로파일과 지속 개선 후보 구현은 D-656 Task 6의 0~5 receipt 관문 뒤다. 지금은 실제 provider를 호출하거나 자동 학습 정책을 승격하지 않는다.
