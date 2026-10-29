# 나머지 Fleet 절차 문서의 컴포넌트·레이아웃 점검

2026-10-28. 기준 commit `c1af578c38`. 기존 `fix/recording-learning-handoff` 워크트리를 재사용했다. 최초 공통화 source commit `90954be599`, ADR 형식 보완 commit `ceb0a14e9a`, 정책 빈 상태 후속 commit `c93066516d`, 최종 제품 source commit `e68f63d769`다. [앞선 네 화면 검증](../fleet-components-layout-tokens-2026-10-28/result.md)을 잇는다.

## 구현과 범위

계정 관리·내 계정·로그인·정책·학습 진입5문서의 경량 헤더는 `fleet-document-header.html.inc`가 정본이다. D-906의 기존 생성기가 관제용4문서와 함께 처리한다. Learning 서버 치환 슬롯은 그대로 두고 고정 헤더 슬롯만 합성한다. `fleet_components.py --check`가9문서의 드리프트를 거절한다. 첫 응답부터 완성된 HTML이며 새 프레임워크나 런타임 합성을 추가하지 않았다.

[D-909](../../adr/D-909-fleet-procedure-document-components.md)의 공통 문서 CSS가16px inset·grid·최소 폭·줄바꿈·container를 소유한다. 인증32rem·학습48rem·정책56rem의 서로 다른 읽기 폭을 역할 토큰으로 유지한다. 정책 입력36rem·근거 높이12rem·로그인 신원10rem도 사용 중인 역할로 이름 붙였다. 값은 tokens.css에만 두고 갤러리는 계산된 값을 표시한다.

긴 호스트 값은 기존 `dl.ui-readout`의 한 열 전환/줄바꿈을 사용한다. 번호 단계의 제목과 설명은 같은 grid 항목에 묶었다. 계정 ID·앱 복귀 URI는 전체 값을 유지하면서 문서 안에서 줄바꿈한다. 스타일을 등록된 asset으로 제공하며 CSP·URL·인증/정책 API를 바꾸지 않았다.

화면 검토에서 추가로 확인한 정책 빈 상태는 미등록·401·503에 승인/사고 폼을 보이지 않게 보완했다. 성공한 상태 응답에서 기존 역할별 렌더를 적용하며 입력 DOM을 보존한다. 빈 선택과 라벨도 첫 응답부터 숨기고 목록이 있을 때만 표시한다. 미등록이면 설치 담당자에게 등록을 요청하도록 안내한다. 기존 두 사람 승인·사고 잠금 규칙은 서버와 기존 판정 소유에 남는다.

## Skills와 독립 평가

impeccable의 layout/extract/polish 흐름을 기존 Operate 설계에 적용했다. 소스 기반 설계 평가와 detector/시각 평가를 별도 에이전트가 수행했고 서로 결과를 보기 전에 분리했다. 요청이 기존 설계의 계속 구현이므로 새 시각 방향 인터뷰는 생략했다. Questions skipped: 사용자가 기존 컴포넌트·토큰 방식으로 계속 수정하도록 명시했다.

설계 평가는 긴 Learning 값·단계 묶음·계정 문자열과 경량 헤더 복사를 지적했다. Robot/Pilot의 표식·관측/조작 기하와 최소320px는 화면 여백의 중복으로 분류하지 않았다. Learning 작업 앱의 기존 app-shell도 유지했다. 임의 숫자를 전부 토큰으로 바꾸거나 역할이 다른 문서를 같은 폭으로 통일하지 않았다.

최종 `detect --json --scope layout`은0건/exit0이지만 `/common/` stylesheet를 소스 상대경로로 해석하지 못한 경고가122회 있어 변수/색 분석이 불완전하다. 검출0건을 렌더링 수용으로 해석하지 않는다. 최종 로그는 `C:/DevTemp/rosy-ui-remainder/detect-layout-complete.json`과 동명 stderr/exit 파일이다. context의 Platform 문구 인식 경고는 웹 대상으로 해석했으며 제품 문서를 부수적으로 재작성하지 않았다.

## 실제 검사

pytest는 전부 커밋된 source를 공식 `tools/remote/remote_pytest.py`로 시험 PC에 보내 실행했다. 브라우저는 `--` 뒤 `ROSY_RUN_BROWSER_TESTS=1`을 전달했다. 다음 경로는 `C:/DevTemp/rosy-ui-remainder/` 기준이며 각 디렉터리의 `run-*.txt`가 원본이다.

| 범위 | commit | 결과 | 로그 |
|---|---|---|---|
| 가짜 테마 호스트의 secure-context RED | ab82cb846b | 1 failed / 8 deselected | theme-red |
| HTTPS fixture·실패 목록 계약 | 1362fe8363 | 36 passed / 2 skipped | theme-green |
| 긴 값·첫 응답·정본 RED | 3ec676f33e | 26 failed / 5 passed | layout-red |
| 긴 값·5폭/2테마·정본·Learning HTTP·wheel/asset | 90954be599 | 84 passed / skip0 | layout-green |
| 긴 유효 호스트 별도 캡처 | ceb0a14e9a | 10 passed / 15 deselected / skip0 | host-captures |
| 정책 미등록·401·503 RED | c008433499 | 3 failed / 25 deselected | policy-empty-red |
| 후속 상태·실제 두 사람 승인·테마 | c93066516d | 39 passed / skip0 | policy-empty-green |
| 정책 후속 공식27대상 | c93066516d | 1 failed / 7812 passed / 503 skipped | policy-affected-final |
| 빈 선택 제거·공용 컨트롤·실제 승인·정본·wheel/asset | 5a171eaad4 | 83 passed / skip0 | policy-reason-green |
| 첫 응답의 미확인 선택도 숨김 | e68f63d769 | 3 passed / 25 deselected / skip0 | policy-final-states |
| 공식 영향72/2/5대상 | ceb0a14e9a | 8898 passed / 760 skipped / NEW0 | affected-final |
| 공식 브라우저102파일/9묶음 | ceb0a14e9a | 1510 passed / skip0 / NEW0 | browser-final |

기존 테마 실패 원인은 가짜 `http://rosy.test`가 보안 컨텍스트가 아니어서 Fleet의 crypto.randomUUID 초기화가 중단되는 것이었다. 가짜 HTTPS origin과 가용성 assertion으로 복구했다. 제품 보안 제한을 낮추지 않았고 known-failure 행은 고친 commit에서 제거했다. theme-green의2 skip은 실패 목록이 비어 실제 listed ID를 쓰는 비교 사례를 생략한 것이며 Chromium 미실행을 뜻하지 않는다.

정책 후속27대상의1실패는 새 native select.disabled 행이 공용 비활성 사유 계약에 맞지 않는다는 검사였다. 예외 목록/known failure를 늘리거나 검사를 약화하지 않고 빈 선택 그 자체와 라벨을 숨기는 더 작은 UI로 바꿨다. 해당 공용 검사 전체와 정책/설치83건이 통과했고 최종3상태도 다시 확인했다. 그 밖의7812개 통과와503 skip은 앞 source의 실행으로 보존하며 최종 source의 전부 재실행으로 이름 바꾸지 않는다.

실제 긴 값 회귀는 최대96자 계정명, 긴 HTTPS 복귀 URI·이메일, 유효한 긴 hostname,320/390/480/768/1440 및 dark/light를 사용한다. 실제 Fleet 정적 서버와 명시적인 읽기 API fixture를 사용하고 쓰기 요청은 assertion으로 거절한다. 계정 저장/회수와 정책 승인은 기존 실제 원장/서버 브라우저 회귀로 별도 검증한다. JS 비활성 문서의 헤더/테마 존재와 문서 가로 넘침 없음도 검사한다.

`affected --base c1af578c38 --json` 결과는 affected/no escalation이며 FULL 요구를 좁히지 않았다. selection은 `affected.json`에 보존한다. 정책 변경의 별도 선택은 `policy-followup-selection.json`이다. 넓은 브라우저 선택은 browser_scope의102파일을 기존 land.pack/land_browser.chunks의9묶음으로 나눠 공식 remote_pytest.run에 전달했다.9묶음 모두 실제 Chromium을 실행해 exit0이며 각 known_failures 비교는 NEW0/known0/flaky0이다.9개 로그의 통과 수는117/156/206/130/66/152/287/223/173이다. 이 광역 기록과 후속 정책 source의83+3 검사는 구분한다.

최종 source까지 정본 CLI check,9개 커밋 size_range·safety_review·커밋 추가 줄 비밀 검사를 통과했다. 문서 초안 포함 lint는0 error/41 warning(기존 gate 신선도 등)이며 모듈 logs와 생성 index를 갱신했다. 최종 문서 commit 검사는 별도 실행 기록으로 남기며 이 source 실행에 소급하지 않는다.

아래 로그 집합 해시도 파일명 순 `파일명 + 공백 + 파일 SHA-256 + LF`의 UTF-8 SHA-256이다.

| 로그 디렉터리 (`C:/DevTemp/rosy-ui-remainder/` 기준) | 파일 | SHA-256 |
|---|---|---|
| affected-final | 3 | 5a431114a2a870d31c8ccfd12aab040a18ec8b5eddfcb6f84caf029e97e9d967 |
| browser-final | 9 | e5f407d43c8d42f1945f712faf737be1fca85466eff9729579c933a793fdda32 |
| policy-affected-final | 1 | 6425fd0d2f1cc22ccdb8b6b24b3be0e45a7387c30631f1699faea40c009d2865 |
| policy-reason-green | 1 | 220e70a861b2b12be6685f233140b483cb0e3bf0799d3714e5ce13d81f17b15f |
| policy-final-states | 1 | 393515afe901630da328c35ed4d1d9316af079cc8bd1efea2b73c27f93a867bd |

| 선택/기계 결과 (`C:/DevTemp/rosy-ui-remainder/` 기준) | SHA-256 |
|---|---|
| affected.json | ca07d741789a4d75fc59b0994362f190c66835ffdb25734e93a192ed1f478180 |
| browser-targets.json | 370eec47dc0ba30597b5db5175636730e8238e2fa844a9a9debc7c109000d5cc |
| policy-followup-selection.json | 35f0aba7edbe4993d2636b53ba242e25d40437b6d5ed0ce9fec714a2977e513f |
| detect-layout-complete.json | 2708be578e03e792e308e41c26495572a8aa7654cb654bca2c5ccccc7c8ef761 |

## 캡처와 검토

원본 PNG는 아래 외부 디렉터리에 두고 Git에 넣지 않는다. SHA-256은 파일명으로 정렬한 `파일명 + 공백 + 파일 SHA-256 + LF`를 UTF-8로 이어 계산한 집합 해시다.

| 디렉터리 (`C:/DevTemp/rosy-ui-remainder/` 기준) | PNG | SHA-256 |
|---|---|---|
| screenshots-red | 20 | d236409b0e8b804a5565899d7c158e0449777e97f104edb9cbb850ab1177b6f6 |
| screenshots-green | 50 | b0cc3474ba10203fdc8fdc8073fac15a0ff09d0742699886985a262423086d3e |
| screenshots-host-green | 10 | cbea484ffdc6f9e0f8a6cc55d6fc42fb75f4a196e606a8a0f9c78fb89c14ddba |
| screenshots-policy-final | 13 | 5b71d60526ec3c04a70ee28a00b6f88da0025077c54d3de36c03ff5a1dfa3053 |
| screenshots-policy-verified | 3 | 8e6dad8c3a053931b7ea971a2d8490af2cb358bd6abfa111872e953b6adbbed4 |

독립 검토는 초기 새 캡처60/60장(일반5문서×5폭×2테마50장, 긴 host5폭×2테마10장), 수정 전4/20장, 중간 정책13/13장, 최종 정책3/3장을 실제로 열었다. 마지막3장은 빈 label/select까지 없는 최종 source의200/401/503 상태이며 앞13장은 중간 근거로 보존한다. 긴 host가 카드 밖으로 넘던 모습이 사라졌고 좁은 로그인/헤더의 바깥 여백이 정리됐다. 작업셀 미등록의 다음 행동도 확인했다. P1/P2 잔여 잘림·겹침 지적은 없다.480px 긴 호스트의2열 배치는 여러 줄이 길어지지만 값/동작은 유실되지 않았다. 계정 캡처는 긴 행 선택 뒤 자동 스크롤된 상태이므로 상단이 보이지 않는 것을 잘림으로 분류하지 않았다.

소스 독립 검토는 공통화와 정책 후속 둘 다 P1/P2·불필요한 추상화 지적이 없었다. 실제 키보드/스크린리더 전 경로, 실물 화면까지 검토했다고 주장하지 않는다.

## 한계와 CE

이 기록은 웹 소스·fixture·시험 호스트의 근거다. 모든 활성 제품 표면의 G2/G3, Android 네이티브·로봇 LCD, 실제 장치/현장 UI 수용은 별도다. 배포·장치 명령·HF 쓰기·추가 push/병합은 수행하지 않았다. 이전 immutable landing은 이번 추가 수정을 포함하지 않는다.

CE: 해당 없음. 보안 컨텍스트 의존성은 시험 assertion/주석에, 긴 값·단계 묶음·미확인 상태에서의 폼 조건은 코드·회귀·D-909에 남아 별도 교훈 없이 복원된다.
