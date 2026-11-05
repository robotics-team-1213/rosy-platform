# 정상 main 병합 뒤 Learning 후속 검증

## 기록 범위

기준은 commit 7893474ba454ef1a8f33a0ee13a18c30232cd338이다. 이 문서는 기존 [동일 위계 검증](hierarchy-followup.md) 뒤에 추가하는 소스별 기록이다. 기존 153개·203개 목록과 당시 결과는 그대로 보존한다. 작성자는 기존 원본을 읽고 해시를 계산했으며 새 시험은 실행하지 않았다.

외부 원본의 작업공간 기준 위치는 `Rosy/docs/workspace-records/2026-11-05/ui-map/`이며, 아래 `review-reports/`, `node-regression-789/`, `learning-merge-padding-0111/`은 그 하위 경로다. `TEMP/`는 실행 당시 시스템 임시 폴더다. 주소·계정·원격 접속값은 전사하지 않는다.

## 병합과 실제 회귀

독립 출처 검토 `review-reports/main-learning-merge-provenance-bdff.md`와 실행 지시 `review-reports/main-merge-execution-brief.md`를 확인했다. UI 부모 commit bdff2d4093116b7a2ecf86838a084707366c3818와 main commit 3caa67b6c324df635189e9af2d094907ee412554의 유일한 공통 기준은 commit 5501425d1dd9b9771b28dec0ec858b91d17167b5다. main 유입은 Learning 46경로이며 guard 자체 7경로와 같지 않다. 그중 옛 UI와 같은 blob 15개를 전체 기능 포함의 증거로 확대하지 않았다.

commit de8f972f67f632e7d56d4f6325d9a21f80b71cda는 Learning 충돌 27경로와 문서 2경로를 정상 병합했다. 양쪽 producer·consumer와 고유 회귀를 함께 보존하고, 문서 로그는 두 계정 원문과 main/UI 추가 항목의 정확한 합집합 2,138개를 유지했다. Ruling 31의 양쪽 부모 비교·실제 병합 소스 검증과 Ruling 32의 저장 전 AI preview 완료 차단을 다음 실행으로 구분한다.

| 실제 소스 | 관측과 후속 |
| --- | --- |
| commit de8f972f67f632e7d56d4f6325d9a21f80b71cda | 첫 AI RED 2 FAIL/NEW 2 중 실제 회귀 1개와 숨겨진 하위 화면의 selector 오류 1개를 구분했다. selector 오류를 제품 결함으로 세지 않는다. |
| commit f3ceffc40fcd3b91775ee75eb9a0945d1ba5eca9 | 결과 control을 유지하는 selector 정정 뒤 RED 1 FAIL/NEW 1로 실제 경합을 확인했다. |
| commit f52885df0009dbb1e98ba8ee73d1cf61f057c2ac | AI feedback과 지연 draft 갱신 분리 뒤 해당 2개 GREEN, 0 skip/NEW 0. |
| commit 0111b08471b16fc42779e2d883461d239c66931d | 미저장 AI preview가 있는데 완료 control이 enabled인 실제 RED 1 FAIL/NEW 1. |
| commit 7893474ba454ef1a8f33a0ee13a18c30232cd338 | 완료 guard 한 줄을 보완했다. 아래 browser·backend·Node는 이 실제 소스에서 각각 실행한 근거다. |

## 기준 소스의 실행별 결과

| 실행 | 범위와 결과 | 원본·receipt |
| --- | --- | --- |
| Browser | 11파일, 385 PASS/0 skip/NEW 0, pytest 1,054.27초. wrapper·runner·classifier exit 0. | `TEMP/rosy-ui-main-merge-browser-cover-20261105/run-1.txt`, `review-reports/main-merge-browser-789-wrapper-receipt.json` |
| Backend | 18파일, 408 PASS/0 skip/NEW 0, pytest 11.47초. wrapper·runner·classifier exit 0. | `TEMP/rosy-ui-main-merge-backend-cover-20261105/run-1.txt`, `review-reports/main-merge-backend-789-wrapper-receipt.json` |
| Node | 2파일 TAP 8 PASS/0 skip/0 fail, Node v18.19.1. pytest known-failure classifier는 N/A다. | `node-regression-789/raw.txt`, `node-regression-789/receipt.json`; own lock·reservation·scope·process 해제 증거 포함 |

독립 근거 검토 `review-reports/main-merge-evidence-review-789.md`는 위 소스와 명시한 범위에서 필수 근거 누락·정정 없음으로 확인했다. 원본·receipt 지문과 실제 실행 소스가 일치하며 JUnit은 요청하지 않았다. 세 실행을 다른 소스의 실행과 합산하거나 공식 FULL로 부르지 않는다. Node의 앞선 추가 SIM 제외 필터 시도는 최종 실행의 근거로 사용하지 않았다. 최종 Node는 정본 배치와 ADMIT을 유지했다.

## 메뉴·여백의 새 렌더와 제한된 alias

commit 0111b08471b16fc42779e2d883461d239c66931d의 실제 메뉴 실행은 14 PASS/0 skip/NEW 0, 33.31초다. `learning-merge-padding-0111/`의 receipt·실행 원본·computed state·원격 원본 목록은 새 PNG 68개와 JSON 62개, 총 130개를 결속한다. 독립 G3 정본 `review-reports/hierarchy-g3-0111.md`는 새 PNG 22개를 직접 열어 여덟 기준 PASS, 새 차단 사항 없음으로 판정했고 130/130 원본을 재해시해 일치를 확인했다. 실제 G3 소스는 이 메뉴 실행 소스이며 Pixel 완료·후속 소스 alias·전체 브랜치 GO는 판정 밖이다.

`consumer-source-manifest.json`과 `source-equivalence-789.json`의 51개 파일을 기준으로 commit 0111b08471b16fc42779e2d883461d239c66931d → commit 7893474ba454ef1a8f33a0ee13a18c30232cd338의 blob·바이트 SHA256이 모두 같다. 범위는 9개 route와 그 static 소비처다. 전체 Learning·Pixel 후보 완료 로직·backend의 동일성이나 이 메뉴 실행에 포함하지 않은 16개 current-path 기능 전체 검증을 뜻하지 않는다.

SIM 320px의 현재 항목은 dark/light 모두 오른쪽 31.453125px가 잘린다(`sim-320-visibility.json`). focus와 focusVisible은 확인했으나 항목 전체 가시성은 false다. 키보드·resize 때 자동 노출은 미검증이며 유지하는 한계다.

## 직접 계산한 원본 지문

다음 SHA256은 receipt 값을 복사하는 대신 존재하는 해당 원본 파일 바이트를 다시 계산했다. 실행 결과와 소스 연결은 각 wrapper receipt에서 별도로 확인했다.

| 원본 | 파일 바이트 지문 |
| --- | --- |
| `TEMP/rosy-ui-main-merge-red-20261105/run-1.txt` | SHA256 `6e7623ef85347e3f1af5ba3bc2ea5c1bb40cb530b0703beee82d7faab1237a32` |
| `TEMP/rosy-ui-main-merge-red2-20261105/run-1.txt` | SHA256 `43bf6ae796d869442517c31052734bbd01d7d935892aec7db34e09a35b402be0` |
| `TEMP/rosy-ui-main-merge-green-20261105/run-1.txt` | SHA256 `dcf8aded76027646163603cc91bb113f36cad9f762a0fd97ff22b7b7488023e0` |
| `TEMP/rosy-ui-main-merge-red3-20261105/run-1.txt` | SHA256 `cc06fad31a244c264efc16a4672a4b6266b2625a907ee0f6413366636cc09ed5` |
| `TEMP/rosy-ui-main-merge-browser-cover-20261105/run-1.txt` | SHA256 `8e07dd12c0d068f5d06fe566203176780eb3283575d7e83f481acf1d5e787821` |
| `TEMP/rosy-ui-main-merge-backend-cover-20261105/run-1.txt` | SHA256 `279c7e871c4f99d4119e6520a9ee35907d4f200584cf4d55eb43e6462d742986` |
| `node-regression-789/raw.txt` | SHA256 `295237f3124dd4123afc81809b2a3f620f750c9a3feb2c9e668d56482aec1c6b` |
| `learning-merge-padding-0111/run/run-1.txt` | SHA256 `c8740dc143633284db9f5fffa712cc25d07001f28cad171802397c0a7a0cacd7` |
| `learning-merge-pixel-final/run/run-1.txt` | SHA256 `ff099ed7ee1638999a6f5a4b8edd83e3130d4c3321a3f87538ce84514da8f405` |

## Pixel 최종 캡처와 제품 동일성

commit 10d7133e66b44153b5e65cf4fa7e8205d3adc087의 실제 AI 실행 `10d7133e66-34b2d1`은 24 PASS/0 skip/NEW 0, 69.55초다. `learning-merge-pixel-final/receipt.json`·`command.json`·`run/run-1.txt`·`classifications.json`·`remote-terminal-status.json`이 소스·실행·분류·종료 상태를 결속한다. own job/worktree/process/marker가 남지 않은 종료 상태를 확인했다. JUnit은 요청하지 않았다.

| 캡처 실행군 | case 수와 관측 |
| --- | --- |
| 미저장 AI 후보 | 6개. 원래 shortcut·focus 흐름 뒤 mask version 1→1, 사람 mask 불변, 저장 상태 pending, preview 선택, 완료 disabled·저장/버리기 enabled를 보존했다. |
| class control·Enter | 12개. 원래 class/Enter 회귀와 실제 renderedTheme 메타데이터를 보존했다. |
| workspace | 2개. 실제 작업공간 상태의 PNG·JSON을 보존했다. |
| decision resize | 2개. 원래 resize 흐름의 기하·상태 PNG·JSON을 보존했다. |
| AI opinion | 2개. 원래 opinion 흐름의 실제 상태를 캡처했다. |

독립 Pixel G3 정본 `review-reports/pixel-g3-10d.md`는 새 PNG 27개를 직접 열고 106개 원본을 전수 재해시해 일치를 확인했다. 관측한 상태의 여덟 기준은 PASS이며 새 차단 사항은 없다. 실제 소스와 앞선 메뉴 G3는 구분한다.

후보 6개 JSON의 document overflow는 0이며 실제 activeElement는 pixel-canvas다. `geometry.focused`를 실제 초점 증거로 세지 않는다. 좁은 화면은 원래 scroll 상태를 유지하므로 저장/버리기/완료 control이 현재 viewport 아래에 있다. 전체 PNG와 DOM rect를 보존했으며 이를 자동 노출·동시 viewport 가시성·실제 scrolling interaction PASS로 바꾸지 않는다. 이 G3는 모델 품질·사람 정답 수용·실물·main 완료를 판정하지 않는다.

`git diff --stat`과 경로 목록으로 commit 7893474ba454ef1a8f33a0ee13a18c30232cd338 → commit 10d7133e66b44153b5e65cf4fa7e8205d3adc087이 정확히 시험 3파일의 56추가/1삭제임을 확인했다: `test_pixel_review_browser.py`, `test_pixel_workspace_browser.py`, `test_review_ai_browser.py`다. 제품 변경 0이므로 전체 제품 blob은 같지만 시험은 바뀌었다. 앞선 385·408·Node 8 결과와 이번 24개는 실행별로 유지한다.

## 새 캡처 목록

[main-merge.sha256](main-merge.sha256)은 외부 `ui-map/` 루트 상대경로의 표준 sha256sum 236행이다. 메뉴 원본 130개와 Pixel 원본 106개(64 PNG+42 JSON)만 포함한다. 실제 파일을 다시 해시해 양쪽 원격 원본 목록과 모두 일치했고 경로 중복은 0이다. 기존 153행·203행 목록은 변경하지 않았다. 목록 Git blob의 LF·마지막 개행 기준 SHA256은 `63025a145175cd897cb913786612d037acd1942ab88965618b1514d1d03f0d15`다. 이 숫자는 산출물 수이며 서로 다른 실행의 PASS 합계가 아니다.

## 후속 수용 대기

선행 main commit 3caa67b6c324df635189e9af2d094907ee412554는 `log-integrity-official-063929/receipt.json`·`land-record.json`·`land-wrapper.log`의 공식 AUTO/FULL에서 pre 38개와 turn 1개, 총 39개 classifier 출력 NEW 0으로 로컬 착지했다. 원본 22개 로그에는 pytest skip이 있으며 quiet 출력에 개별 사유가 없다. guard cache 재사용과 당시 lint 경고도 남는다. 따라서 NEW 0을 skip 0·모두 새 실행·실물 수용으로 해석하지 않는다. 이는 선행 guard 소스의 결과이고 위 UI 기준 소스의 최종 G1·공식 AUTO/FULL·실제 main 착지·배포·실물 수용은 아직 완료하지 않았다. CE: 해당 없음 — 병합 근거·코드·회귀·소스별 원본으로 판단을 재구성할 수 있다.
