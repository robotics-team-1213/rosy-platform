# Fleet 관측 원장 책임 분리와 capture 계획

D-699를 구현한다. 변경 전 Fleet 부모는 54,211줄이며 기존 54,074+150 한도에서 13줄 남았다. CORE event journal 137줄과 ObservationStore 74줄을 실제 `fleet.observe`에 옮기고 새 package init 1줄을 포함한 이전 기준 212줄로 등록한다. 기존 부모 기준과 +150을 유지하며 새 unit도 +150·파일 한도를 유지한다. capture 기능 증가를 기준에 미리 포함하지 않는다.

1. `server/core_event_store.py`와 `server/observation_store.py` 구현을 `observe/events.py`, `observe/store.py`로 옮긴다. 기존 경로는 identity alias로 유지한다. SQLite 연결 정책은 기존 server owner에서 재사용한다.
2. 기존 CLI·Hub·Console·API·오프라인 learning exporter의 import와 예외·transaction·retention을 유지한다. 새 원장은 Fleet의 같은 DB·같은 배포에 포함되며 모델 추론·장치 명령을 추가하지 않는다.
3. 실제 append run/sequence/monotonic/roster를 기존 payload에 추가한다. 증가부터 validation과 commit까지 직렬화하며 실패·빈 roster 뒤의 누락과 restart를 구분한다. 최대 1,024개 roster 행과 기존 64KiB payload 한도를 적용한다.
4. source·설치 alias와 기존 이벤트/API/observations/export·보존 회귀를 원격 시험한다. 실제 새 unit과 부모를 동시에 측정하고 등록된 holder/의존 방향을 검사한다.
5. read-only observation window 도구를 구현한다. 대상 robot만 먼저 filter하지 않고 동일 capture 전체 roster를 검증한다. 누락·retention·양끝·restart·clock 문제는 HOLD다. 관측 capture 범위와 CORE 명령·모델 호출·재발·현장 수용을 구분한다.

새 `fleet.observe`는 source journal 책임이며 새 process나 별도 wheel이 아니다. setuptools find_packages의 기존 배포 closure를 사용한다. ADR 관계는 D-699의 D-427·D-429·D-430 표를 따른다. 원격 시험·독립 검토 후 승인된 local landing만 수행하며 push는 별도다.

## 기록 창 구현과 검사

최신 통합은 commit `0bedd7809c719edb9bdf2e78759bf529b1257e08`로 로컬 main에 착지했다. source·실제 wheel 설치·CLI·기존 caller/API·parent/child 크기·API version alignment와 문서 계약을 포함한 17개 파일은 적격 AI PC 9GB에서 318 passed, terminal exit 0, known-failures NEW 0과 lint를 통과했다. 고정 로그는 세션 `logs/observation-land-0bedd7809c/run-1.txt`다. 아래 착지 전 checkpoint는 당시 상태다. 최종 source 검토는 window/payload/CLI 책임과 privacy 경계에서 중요 blocker가 없었다. 실제 운영 배포·센서 최신성·명령/모델/재발 전체 범위와 현장 수용은 여전히 미확인이다.

기존 `learning/curation/pinky/fleet_observations.py`의 `capture_window`와 `--window` CLI를 재사용 경로로 구현했다. 새로운 operations 역방향 import·서비스·모델 호출은 없다. read-only WAL transaction, 전체 boundary roster, capture run/sequence·clock/cadence, strict canonical finite JSON·privacy·64KiB 입력, 24시간·4,096행 한도를 검증한다. 결과는 ID/hash와 미검수 coverage이며 command/model/recurrence 수치는 null이다. source clock의 오래된 값·offline null은 capture 시계로 취급하지 않는다.

원격 RED는 미구현 함수의 18개 실패와 미연결 CLI의 1개 실패를 각각 확인했다. `07419256c`의 window·기존 관측/export·capture·holder/size 5개 파일은 적격 AI PC에서 87 passed, terminal exit 0, known-failures NEW 0이다. 단독 CLI는 `python -I -S`로 실행하고 출력 재사용을 거절했다. 로그는 세션 `logs/observation-window-cli-green/run-1.txt`다. 독립 검토와 최신 main 통합·local landing은 다음 gate이며 실제 서비스 배포·현장 수용·정상 무명령·재발 0건을 입증하지 않는다.

## 이전·기능 추가 후 동시 측정

최신 main 통합 commit `0bedd7809c`의 동일 생산 필터 독립 실측은 Fleet 부모 55,460줄 / 기존 main 독립 검토 기준 55,664+150 = 55,814, observe 232줄 / 이전 기준 212+150 = 362다. 기존 events 137+store 74가 부모에서 빠지고 aliases 5+2만 남아 부모 감소는 204줄이다. capture 증가 20줄은 child에만 계산한다. 동료가 검토한 main 기준과 observe 이전 기준을 올리지 않았으며 통합 source·충돌 보존 검토에서도 중요 blocker는 없었다. 이전 아래 실측은 그 당시 main 기준이다.

`1a1df82325`의 기존 source 필터 실측은 Fleet 부모 54,007줄(기존 54,074+150 = 54,224 한도), observe 232줄(이전 기준 212+150 = 362 한도)이다. aliases는 각각 5·2줄이며 CORE event body는 SQLite 정책 import 외에는 그대로 유지했다. 독립 검토에서 실제 동일 DB 원장 책임 분리와 기준 유지에 동의했고 중요 source blocker를 찾지 못했다.

같은 후보의 capture·기존 observation/export·Core event/API·Hub와 ownership/size를 포함한 7개 파일은 적격 AI PC 9GB에서 원격 79개 시험과 known-failures 신규 실패 0건, lint를 통과했다. 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/observation-capture-green/run-1.txt`다. `8dfb4be989`의 실제 wheel build→별도 target 설치→`python -I -S`의 source 없는 import·identity alias·DB capture와 capture 회귀는 적격 Model PC에서 6 passed, terminal exit 0, known-failures 신규 실패 0건이다. 설치 로그는 같은 세션의 `logs/observation-installed-green/run-1.txt`다. 이는 direct wheel 증거이며 sdist·read-only window·로컬 착지·실제 배포·현장 수용은 미완료다.
