# 녹화·검수·학습·HF 보관 연결 검증

2026-10-28 KST. 브랜치 `fix/recording-learning-handoff`. 기준 commit은 `fedd349e37b0dc41c0ab222d2d450e50c26656c3`, 최종 제품 소스 commit은 `55117575a3331d886963f4b97631c18f19c25416`이다. 이후 `79c0c58074`까지는 키보드 회귀 시험만 보강했으며 제품 디렉터리의 diff가 0임을 확인했다. 이 기록과 생성 색인은 문서 변경이다.

## 판정과 구현

검수·변환·고정 자료 보관 인계를 구현하고 원격 소스/계약/패키지·HTTP·Chromium 회귀로 확인했다. 실물 녹화부터 HF 게시·reader 검증·학습·현장 적용까지 모두 UI에서 완료됐다는 판정은 아니다.

- 미저장 검수는 취소한 새로고침·자료 변경에서 보존한다. 저장 중 자료 교체, 실패한 저장, 확인 중 추가 편집을 보호한다. 실패/성공 재로딩 후에도 선택한 저장 검수의 뜻을 유지하며, 현재 원본과 맞는 검수가 없으면 변환을 막고 명시적 선택을 요구한다.
- 변환 진행·실패·완료와 결과 자료 ID/revision을 제출한 4단계에서 보여 준다. 완료 자료에서 학습 또는 해당 고정 자료의 보관 준비로 이동한다. 학습 실행 목록과 중복 표시하지 않는다.
- 등록된 OMX 자료를 서버가 프로젝트·고정 revision·전체 바이트와 대조한다. 허용 파일만 별도 export 폴더로 복사하며 원본은 보존한다. 심볼릭/하드 링크·경로 이탈·변조·타 프로젝트·부분 복사 충돌을 거절하고 동일 작업 재시도는 검증 후 재사용한다. 상한은 1,000파일/512 MiB다.
- 링크/GET은 쓰기나 전송을 하지 않는다. 보관 화면이 자료·revision을 표시하며 사용자의 완료 확인과 기존 권한·CSRF·private 대상 가드를 요구한다. 누락된 revision을 다른 자료로 대체하지 않는다. 수동 선택 후 새로고침도 해당 자료를 다시 확인하고 동의를 초기화한다.
- Pinky MCAP, OMX native LeRobot 준비, ROSY ACT 학습 자료와 HF 바이트 보관의 의미를 나눠 안내한다. signed runtime inventory에 새 서버 모듈과 JS를 포함한다. Learning host 기존 API body 변경을 API v1.328에 등록했다. CORE envelope 1.0은 변경하지 않았다.
- HTTP 이름의 Chromium 저장 시험도 공식 브라우저 선택에 포함했다. 이 선택기 변경으로 FULL이 필요해졌으며 축소하지 않고 전체 행렬을 실행했다.

동작과 제약의 정본은 [저장 안내](../../../learning/curation/perception/docs/storage-pool.md)와 [API 명세](../../reference/ROSY%20API%20%26%20Protocol%20Reference.md)다.

## 전체 원격 회귀

공식 `rosy_harness.py affected --base fedd349e37 --json` 결과는 FULL이며 사유는 `test/browser_scope.py: harness configuration or the selector itself`다. 보존한 [26개 invocation](evidence/full-selection.json)은 원본 `full_invocations`와 같다. 이 파일의 SHA-256은 `431ff032d5c6821f6deab9e399ef4d11599485d62eb45d90a1ef4d1940e9761d`다.

메타데이터 정정(2026-10-28 후속 UI 검증): 두 Git 객체를 `git cat-file -t`로 확인하고 JSON의 `base`/`tested` 이름을 `base_commit`/`tested_commit`으로 명확히 했다. 원래 파일 SHA-256은 `c9ba2e560c49a7414d06e9e9af375547416d704735a1490295d034cde42da387`다. 커밋 값·실행 행렬·원본 로그·시험 결과는 변경하지 않았다. 새 보안 검사의 비밀값 오탐을 검사 예외나 baseline 추가 없이 바로잡은 표기 정정이다.

`remote_pytest.py --affected-json`은 FULL에서 guard만 고르는 현재 동작이 있으므로, 공식 `remote_pytest.run()`에 전체 26개를 그대로 전달했다. 실제 실행은 외부 selection JSON을 읽었으며 아래는 보존본으로 같은 실행을 구성하는 코드다. 노트북 pytest는 실행하지 않았다.

```python
import json, sys
from pathlib import Path
sys.path.insert(0, 'tools/remote')
import remote_pytest as runner
selection = json.loads(Path('docs/validation/recording-learning-handoff-2026-10-28/evidence/full-selection.json').read_text(encoding='utf-8'))
invocations = selection['full_invocations']
logs = [Path('C:/DevTemp/recording-learning-handoff-full-final') / f'run-{i}.txt'
        for i in range(1, len(invocations) + 1)]
codes = runner.run(invocations, logs, sha=selection['tested_commit'], wait=3600, poll=30)
sys.exit(runner.worst(codes))
```

승인된 모델/AI 시험 호스트에서 종료 코드 26개 모두 0이다. 첫 실행의 invocation 합계는 **36,657 passed / 2,297 skipped / 1 failed**다. 중복 선택된 시험이 있어 고유 시험 수는 아니다. 실패한 기존 quarantine의 `test_real_uds_round_trip_stays_inside_the_bound`는 공식 자동 재시도 1회에서 통과했다. 모든 원본 로그를 `python test/known_failures.py <log>`로 비교한 결과 **NEW0 / known0 / flaky1**이다. 재시도 통과를 첫 실행 무실패로 바꾸지 않았다. [원본별 결과와 SHA-256](evidence/full-log-manifest.md)을 보존했다.

2297 skip에는 opt-in Chromium·SDK·학습 환경 등에 의존하는 시험이 포함된다. 이를 실행 또는 수용으로 계산하지 않는다. 별도 Chromium 실행은 다음 절의 범위만 검증한다. 비교기에 항상 표시되는 기존 theme 시험의 “listed but not failing”도 해당 시험 실행 증거가 아니다.

## 대상 회귀와 실제 화면

모든 pytest는 `python tools/remote/remote_pytest.py --sha <commit> --log-dir <dir> -- <targets>`로 수행했다. Chromium은 runner의 `--` 뒤에 `ROSY_RUN_BROWSER_TESTS=1`을 지정했다. 아래 로그 경로의 기준 폴더는 `C:/DevTemp/`다. 표의 GREEN 로그 비교는 모두 NEW0이다. 행별 실행은 겹치므로 합산하지 않는다.

| 범위 | 커밋 | 결과 | 로그 |
|---|---|---|---|
| 검수 revision·보호 및 Center HTTP | f836d5f7e2 | 16 passed / skip0 | recording-learning-handoff-review-revision-green/run-1.txt |
| 변환 상태 2종 | f87678585f | 2 passed / skip0 | recording-learning-handoff-conversion-green/run-1.txt |
| 소스·signed runtime closure | 0f76cb9a4e | 255 passed / skip0 | recording-learning-handoff-package-green/run-1.txt |
| 보관/setup 실제 HTTP·Chromium | 29046060c7 | 9 passed / skip0 | recording-learning-handoff-archive-ui-green-2/run-1.txt |
| 선택기와 추가 소스 edge | 8cd3006fcc | 30 passed / skip0 | recording-learning-handoff-browser-selection-green/run-1.txt |
| 저장 job 실제 HTTP·Chromium | 8cd3006fcc | 8 passed / skip0 | recording-learning-handoff-storage-browser-extra/run-1.txt |
| 수동 자료 선택 후 새로고침 | 55117575a3 | 9 passed / skip0 | recording-learning-handoff-storage-refresh-green/run-1.txt |
| Pilot·Robot·OMX·Learning 광역 Chromium | b9ba4d5018 | 479 passed / 1 failed / skip0 | recording-learning-handoff-browser-green/run-1.txt~run-4.txt |
| 키보드 지연 응답을 포함한 review flow 전체 | 79c0c58074 | 148 passed / skip0 | recording-learning-handoff-keyboard-race-green/run-1.txt |

광역 Chromium은 승인된 site TEST 호스트에서 격리 fixture 서버를 사용했다. 그룹별 결과는 167/47/40 passed와 225 passed/1 failed다. 보관 전송은 fake HF transport이며 실제 HTTP 서버와 Chromium을 사용했다. 기존 실제 계정/HF나 운영 서버를 호출한 수용 시험이 아니다.

실패한 keyboard start→stop 시험은 상태 문구가 먼저 갱신되고 저장 현황 요청이 끝나기 전에 다음 명령을 보내는 경우였다. 기존 기준/현재 단독 실행은 각각 3 passed였지만, `341b05bba0`에서 브라우저 fetch 응답을 1초 지연하자 세 크기 모두 같은 실패를 재현했다(`recording-learning-handoff-keyboard-race-red-2/run-1.txt`). `79c0c58074`는 명령마다 실제 대상 버튼 활성화를 검증하고 기존 키보드 조작·결과 검증을 유지한다. 마지막 5초 폴링 확인은 8초 제한을 사용한다. busy 중 명령 거절이라는 제품 동작을 변경한 것이 아니다. quarantine 목록도 변경하지 않았다.

실제 PNG 네 장을 내려받아 읽기 전용 독립 화면 검사와 소스 대조를 했다. 위치는 `C:/DevTemp/recording-learning-handoff-screenshots/`이며 원본 캡처는 커밋하지 않았다. 캡처는 b9ba4d5018의 fixture 화면이다. 이후 제품 변경은 수동 보관 선택 재확인 한 줄이며 해당 동작은 최신 9개 브라우저 회귀로 검증했다.

| 파일 | SHA-256 |
|---|---|
| omx-archive-320-light.png | 6ea95c0edac95b3f458c49c61e1dec538e981f7ae8fa5dcb1d6c3ebb232ee75a |
| omx-archive-1440-dark.png | 07a5d0d39e1af726f54a2429bfe6a1d0c01e941d6a236915837b041d83ddf6bb |
| recording-learning-review-saved.png | b32e91f86893cca82fb61669162f1f9e960f8da6b7d40b24676f77fa172ffed3 |
| recording-learning-review-unsaved.png | b8afb30481df780b52b97cb394c51308723648f05655b089f9f09d2bb9a1a691 |

320px/light에서 자료·고정 버전·동의·버튼이 세로로 쌓이고 긴 revision은 가용 폭 안에서 줄바꿈된다. 1440px/dark에서는 원본 보존·별도 사본·바이트 검증과 학습/현장 수용의 구분을 함께 읽을 수 있다. 미저장 검수 캡처는 저장 검수 선택 비활성과 설명을 확인한다. 저장 후 캡처는 선택 상태·ID·변환 버튼 위치를 포함하지 않으므로 그 연결은 브라우저 동작 시험 근거로만 판정한다.

잔여 P2 관측: 전체 도구를 펼친 검수 캡처는 본문 4단계와 왼쪽 hash 기준 1단계 강조가 다르다. 전체 도구 스크롤과 선택 표시의 기존 차이일 수 있으며 이번 변경 회귀로 단정하지 않았다. 작은 보조 설명의 정량 대비·전체 키보드 접근성 감사는 하지 않았다. 최초 소스 기준 21/40 전체 점수는 갱신하지 않는다.

## 실패·중단 보존과 리뷰

- 최초 broad affected(b9ba4d5018)는 5 failed / 7,874 passed / 557 skipped였다(`recording-learning-handoff-affected-green/run-1.txt`). 누락한 Fleet API 고정값 5개를 v1.328로 맞췄고 FULL Fleet 7,233 passed에서 확인했다.
- 55117575a3의 guard 실행은 2 failed / 8,005 passed / 557 skipped였다(`recording-learning-handoff-affected-final-2/run-1.txt`). 충전 파이프라인 shutdown_UNDOCKING/shutdown_CHARGING의 간헐 실패다. 같은 제품 커밋의 FULL Gateway 묶음은 7,775 passed / 91 skipped였고, 기준 fedd349e37의 해당 두 파일은 9 passed였다(`recording-learning-handoff-station-baseline/run-1.txt`). 원인은 해결했다고 주장하지 않으며 baseline/quarantine에 추가하지 않았다.
- 검수 성공 reload에서 검수 없는 새 revision이 원본 선택으로 바뀌는 버그를 원격 RED 2건으로 재현하고 f836d5f7e2에서 고쳤다. 실패 reload의 선택 유실, 소스/패키징과 화면 동의 가드의 RED도 원래 로그에 보존했다.
- 서버 재시작 전 Task1의 기존 remote rc143 중단은 통과 증거에서 제외했다. 관측 시간 초과만으로 실행을 재시작하지 않았다.
- 독립 전체/후속 코드 리뷰에 남은 Important/Critical 지적 없음. 최신 수동 선택 수정과 시험 동기화 보강도 별도 검토했다. Harness lint 0 errors / 45 warnings, size_range는 79c0c58074까지 26 commits checked다. warnings는 기존 gate 이력/작업 공간 상태이며 깨끗한 운영 수용을 뜻하지 않는다.

## 수용 범위와 다음 실제 확인

[기존 SIM 데이터 실제 HF 왕복](../omx-hf-private-roundtrip-2026-10-24/result.md)과 [모델 왕복·재적재](../omx-hf-model-roundtrip-2026-10-24/result.md)는 이전 고정 자료의 별도 증거다. 이번에는 이를 새 UI의 실물 녹화·실제 HF 업로드 성공으로 재사용하지 않는다.

Pinky MCAP와 common Episode는 LeRobot 게시물과 같지 않다. OMX 현장 수집/교정은 기존 CLI/owner 경로이며 새 UI 실물 녹화 수용은 남아 있다. native LeRobot 검수 후 변환 자료는 ROSY ACT 학습 형식이고, 이번 HF 보관은 파일 바이트 검증이다. 원격 보관 성공은 LeRobot reader·모델 품질·장치/현장 승인을 뜻하지 않는다.

실제 수용에서는 사람이 고른 완료 실물 녹화의 provenance를 고정하고 검수·변환·private HF 전송/재다운로드/형식 reader를 단계별 확인해야 한다. 정책 품질·실물 행동은 별도 수용이다. 이번 작업에서 실물 명령, 실제 HF 쓰기, 운영 SDK/의존성 설치, payload 설치·배포, main merge·push는 수행하지 않았다. 사용자 승인으로 만든 작업 워크트리와 커밋을 보존한다.

CE: 해당 없음 — 원인·방어 경계·회귀와 시험 동기화 판단이 최종 코드·시험·기존 저장 안내에 보존되어 별도 교훈이 필요하지 않다. 충전 파이프라인 간헐 실패의 근본 원인은 미해결로 남긴다.
