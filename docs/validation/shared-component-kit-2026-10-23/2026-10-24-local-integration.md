# 공통 UI 부품 — 로컬 main 통합

2026-10-23–24. 사용자는 검증 뒤 로컬 main 통합을 승인했다. push·배포는 범위에 포함하지 않았다. [구현 기록](result.md)과 [최종 수정 검증](2026-10-23-final-checks.md)은 당시 커밋의 동결 기록으로 그대로 보존한다.

공통 라이브러리와 Fleet·Robot 적용을 세 착지 단위로 로컬 main에 반영했다. 최종 실행 코드와 새 화면 증거의 기준은 `2d9acbfa51`이다.

## 착지 단위

| 범위 | 후보 브랜치·커밋 | 착지 결과 |
|---|---|---|
| 공통 부품·견본·공개 기준 | `uiux/component-kit-integration`, 원본 `410167aba5` | `1fd406e367` 로컬 main 착지 |
| Fleet 선택 이동·동작 모음·닫힌 CSS 목록 | `uiux/component-fleet-integration`, `9afdedbef1` | `3cbe3b78cd` 로컬 main 착지 |
| Robot 웨이포인트 필드 오류·실패 입력 보존 | `uiux/component-robot-integration`, `1f5e8e0d4c` | `2d9acbfa51` 로컬 main 착지 |

공통 라이브러리는 제품 적용과 분리했다. 17개 파일은 한 공통 패키지의 실행·설치·견본·시험·공개 사용 기준이다. Fleet는 모듈 로그·생성 색인을 포함해 10개, Robot은 5개 파일이다. 각 실행 소스와 시험은 이전 최종 `37951c2501`의 해당 Git blob과 같다. 최신 main은 공식 착지 도구가 각 후보에 병합하고 회귀를 수행한다.

## 검증

착지는 `python tools/land.py --tests auto --no-prune`의 대기열·안전 검토·크기·lint·원격 pytest·known-failure 비교·fast-forward 경로를 따른다. 노트북에서 pytest나 브라우저를 실행하지 않는다.

| 별도 고정 SHA 실행 | 결과 |
|---|---|
| `410167aba5`: shared/web 전체, 브라우저 활성화 | 391 passed / 1 skipped / 2 warnings |
| `9afdedbef1`: Fleet 적용·대기열·지도·CSS 경계, 브라우저 활성화 | 115 passed / 2 warnings |
| `1f5e8e0d4c`: Robot 준비·폼 회귀, 브라우저 활성화 | 3 passed |

`1fd406e367` 공통 라이브러리 착지의 guard는 273 passed, 기본 영향 선택은 1,168 passed / 370 skipped, 브라우저 묶음은 각각 288·375·429·200 passed다. 브라우저 묶음 합계 1,292건은 skip 0이며 모든 착지 로그의 known-failure 비교는 0 NEW다. 기본 선택의 skip을 실행으로 계산하지 않고 명시 활성화한 브라우저 묶음과 구분한다.

`3cbe3b78cd` Fleet 착지는 guard 273 passed, 기본 두 호출 4,657 passed / 327 skipped / 하위 단언 5건 및 6,499 passed / 333 skipped다. 브라우저 네 호출은 118·185·105·119 passed로 합계 527건, skip 0이다. 모두 0 NEW로 착지했다. 작업 로그·생성 색인 두 파일은 공식 도구가 자동 병합했다.

`2d9acbfa51` Robot 착지는 guard 273 passed, 기본 영향 선택 1,303 passed / 402 skipped다. 브라우저 네 호출은 91·34·47·81 passed로 합계 253건, skip 0이다. 모두 0 NEW로 착지했다.

같은 `2d9acbfa51`의 새 캡처 실행은 shared/web 전체·Fleet 적용·교통·Robot 준비/폼 회귀 407 passed / 1 native token export skipped / 2 warnings, 별도 Robot 전체 UI 셸의 합성 저장·재조회 1 passed / 2 warnings다. 두 로그 모두 0 NEW다. 후보를 고정해 검증했고 같은 SHA가 main에 착지했다.

shared skip은 기존 native token export의 별도 opt-in이다. Fleet 첫 별도 명령은 잘못 지정한 시험 파일명으로 collection 전에 exit 4·0 tests였고, 실제 파일명으로 수정한 로그를 분리했다. 이 명령 오류를 성공이나 제품 회귀 실패로 계산하지 않는다. 각 착지의 skip·재사용 범위와 합계는 원시 로그를 따른다. 중복 실행 수를 고유 시험 수로 더하지 않는다.

이전 화면 증거 24장과 실행 로그는 `Rosy/docs/workspace-records/2026-10-23/component-expansion-evidence/manifest.json`으로 보존한다. 이번에는 `2d9acbfa51`에서 새 PNG 36장(UI·지도 35장, Robot 전체 UI 셸 1장)을 생성했고, 회수본 모두 원격 원본과 SHA-256이 일치한다. 390px 확인과 정지, 320px Fleet 선택 이동, 390px Robot 저장 결과를 직접 확인했다. Fleet 이미지의 Vision 404는 합성 API fixture 응답이며 실제 Vision 서비스 점검 결과가 아니다. 오류 상태의 Robot PNG 한 장은 격리 패널로 구분한다.

이번 증거는 `Rosy/docs/workspace-records/2026-10-24/component-integration-evidence/`에 보존한다. `runtime-manifest.json` SHA-256: `09ec96e32478f54268f7ce5bad37ba8ca653b9af42158d52f89bfc93a024738a`.

이 manifest는 실행 자산 19개·핵심 시험 파일 4개가 기존 최종 `37951c2501`과 같은 Git 내용임을 확인하고, 각 소스의 Git object id·내용 SHA-256·Windows 체크아웃 SHA-256을 구분한다. 착지 영수증·원시 로그·캐시 전 선택 JSON·새 캡처·이전 검토 기록·이력 bundle의 해시도 묶었다. 서로 다른 SHA의 시험이나 캡처를 최종 HEAD에서 다시 실행한 것으로 계산하지 않는다.

원래 RED·검토·수정 이력은 `Rosy/artifacts/worktree-backups/component-integration-2026-10-24/verified-component-history.bundle`에도 보존했다. `git bundle verify` 통과이며, tip은 `37951c2501`, 복구 전제 커밋은 main 이력에 있는 `1f47f20905`다. bundle의 SHA-256은 이번 증거 manifest에 기록한다.

독립 검토는 앞선 기록의 명시 범위에 해당한다. 이번 변경 분리·main 병합에 대해 새 독립 검토를 수행한 것으로 표현하지 않는다. GitHub 게시를 할 때에는 그 최종 head에 대한 프로젝트 검토·CI 절차를 다시 따른다.

## 작업 공간 복구와 남은 범위

첫 착지 대기 중 작업 디렉터리의 파일과 Git 등록이 사라진 것을 관측했다. 제거 주체·명령은 확인되지 않았다. 커밋·브랜치와 Git 밖 증거는 남아 있었고, 도구는 기준 SHA 불일치를 감지해 main 갱신 전에 중단했다. 같은 커밋을 공식 gateway로 복구하고 진행 중 잠금을 설정했다. 조사 중인 원인을 해결된 사실로 기록하지 않는다.

CE: 미해결 — 작업 공간 복구는 확인했으나 제거 원인은 미확인이다. 관측·가설·다음 확인은 저장소 밖 `component-integration-progress.md`에 보존한다. UI 구현 자체의 판단은 기존 코드·회귀 시험으로 설명되어 별도 해결 교훈을 추가하지 않는다.

로컬 main 반영은 push·CI·배포·실물·실제 사용자 과업 G3·현장 수용을 뜻하지 않는다. 카탈로그 검증 상태인 선제 부품은 제품 사용 시 자료 소유자·권한·서버 검증을 연결해야 한다.
