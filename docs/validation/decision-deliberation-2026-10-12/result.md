# D-640 후보 전용 숙고 SOURCE 검증

날짜: 2026-10-12. 기준 source: `8036d90c09`.
시작 main: `4bcfc55d8`. 사용자 범위: Discord 제외 나머지 진행, 기존 로컬 병합 승인.

Decision supervisor/고정 CLI 번역, Fleet 기존 DB의 advisory journal,
기존 offline 비교 도구와 installed wheel/sdist 경계를 구현했다.
두 모델 독립 의견·한 번 반론, 최대 세 호출/전체 30초, 현재 사건·TTL,
비개입 zero-call, 불명 비용 HOLD, durable 의견/종료·재시작 거절을 검사했다.
평가는 동일 독립 세트, 전역 녹화 중복/학습 누출, 고정 mode별 모델·정책 revision,
사람 검수·최소 건수·오류/지연/비용 한계를 요구한다. 임의 현장 한계는 만들지 않았다.

원격 integration terminal exit0, **210 passed, known failures 0 NEW / 0 known**.
모델 PC에서 실행했고 노트북 pytest는 실행하지 않았다. 재현 suite:

```powershell
python tools/remote/remote_pytest.py --log-dir <X-session>/logs/integration -- operations/fleet/test/test_deliberation.py operations/fleet/test/test_cli_deliberation.py operations/fleet/test/test_deliberation_journal.py operations/fleet/test/test_deliberation_replay.py test/test_remaining_platform_installed.py test/test_decision_replay.py test/architecture/test_module_structure.py test/test_harness_contracts.py operations/fleet/test/test_model_tool_call_journal.py operations/fleet/test/test_mission_model_turn_store.py operations/fleet/test/test_mission_feedback_loop.py -q
python test/known_failures.py <X-session>/logs/integration/run-1.txt
```

원시 로그: `X:/DevTemp/projects/rosy-platform/2026-10-11--234333--model-deliberation--83396a/logs/integration/run-1.txt`.
앞선 tests/source RED→GREEN과 버전/help 읽기 기록은 같은 X 세션에 보존한다.
lint는 오류0이며 기존 모듈의 오래된 last_verified 등 경고25건은 해당 모듈 수용 증거가 아니다.
독립 검토자 responsibility_review는 source blocker 없음과 Fleet52019/Decision231
재측정·단위/부모 동시 재판정을 확인했다. 예산·기존 추출 의무를 유지한다.

**범위:** fake provider 계약, 설치 배포물 import, 구조/문서·기존 Mission 원장 회귀 GO.
모델 PC의 help/version은 읽기 증거만이다. isolated launcher는 필수 주입이지만
실제 OS 격리/CLI JSON smoke/provider ID/비용 상한 검증과 모델 추론은 미실행이다.
trusted programmatic 진입점만 있으며 Fleet worker/HTTP 실제 모델 자동 연결은 없다.
실제 Pinky 독립 정답·프로파일·FIELD는 팀 검수 뒤 진행한다. 운영 활성화 HOLD.
Discord 설정·발송, push, 배포, 로봇 주행·정지 해제는 수행하지 않았다.
이 receipt 자체는 로컬 FF 성공·CI·FIELD 증거가 아니며 착지는 이후 land terminal로 확인한다.
