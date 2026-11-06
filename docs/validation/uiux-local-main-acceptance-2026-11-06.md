# UI/UX 로컬 main 수용 — 2026-11-06

아티팩트 `ER6vefvBnSjdAn3Pwx5iLW`를 기준으로 한30개 화면의 UI 변경은 로컬 main commit `a4139efa7eff6fc780f8889a6dbc4475afd5adb7`에 공식 AUTO 절차로 수용됐다. 실행 tree는 `1fdb6103e1bc074dd8118d11edad1a9601f87033`다. 이 문서는 수용된 제품 소스를 기록하며, 이 문서 자체의 이후 착지 SHA와 제품 소스를 혼동하지 않는다.

## 수용한 범위

같은 위계·역할의 메뉴는 공용 부품과 토큰으로 선택 배경·높이·여백·정렬·모양·현재 위치·초점 표시를 통일했다. Fleet 지도와 설치의 하위 메뉴 차이도 이 범위에 포함한다. 메뉴의 링크·탭·버튼 의미, 실제 권한과 안전 사유, 미저장 입력, 탐색·뒤로 가기·확인 흐름은 유지한다. 화면별 질문·상태·뷰포트·원본 촬영·제한은 기존 [표면 기록](uiux-surfaces-2026-11-05/surfaces.md), [같은 위계 후속](uiux-surfaces-2026-11-05/hierarchy-followup.md), [통합 근거](uiux-surfaces-2026-11-05/final-closure.md)를 따른다. 과거 frozen 기록의 대기·실패를 소급해 고치지 않는다.

30카드 중29개는 선언된 관찰 범위의 UI 검증 대상이고 공용 갤러리1개는 DEV다. 별도 backend/운영 후속13개와 실제 모델·장치·현장 수용은 UI 구현 완료로 생성하지 않는다. 화면별 최초 기동·빈 목록·연결 상태·인증/거부·오류·안전/확인 셀의 적용 범위와 N/A 근거는 기존 카드에 보존한다.

## 실제 공식 착지

- 제출 소스 commit: `f865013a29026b1e36cc4d63c4b1d83568a84e54`. Native가 trusted main252와 정상 병합한 실제 시험·착지 소스는 위 a4139다. UI·API·Pixel 준비 상태·Cell 촬영 입력은 제출본과 동일하다는 독립 소스 검토를 마쳤다.
- 공식 브랜치: `land/uiux/record-restack-20261106004227`, 요청 명령 `python tools/land_async.py --tests auto`.
- 2026-11-06 02:02 UTC 종료 관측에서 정확한 브랜치의 `landed`, `main_move: true`, 실제 main SHA와 reflog의 fast-forward가 일치했다. 제출 소스의 main ancestry도 exit0이다.
- 네이티브 준비에서 새 producer19건(guard3+pre16), 마지막 라운드에서321PASS/87warnings의 새 producer1건을 보존했다. 마지막 라운드 재사용14건은 동일 tree13건과 기존 e669 소스1건이다. 준비의 재사용53건 역시 원래 e669 실행 출처를 유지한다. 재사용·추가 시험을 새 네이티브 실행으로 합산하지 않는다.
- 보존된 준비 record의 tier는 null이다. 실제 로컬 AUTO 수용을 게시용 qualifying FULL로 바꾸지 않는다. 착지 후 준비 record가 삭제된 것은 종료 전 복사본과 구분한다.

로컬 작업 공간의 `2026-11-05/ui-map/official-ui-004227-in-progress/checkpoint-20261106T020230Z/receipt.json` SHA256은 `9b35664ab1a9d57beca531111cbd7442fe2624b07ae69a8ca67f877c501f2746`, 마지막 라운드 raw SHA256은 `8466cdcb9ccf4ae4a673a2ea3924be4617b735cf387040e8b255f0937c1d45f5`다. 종료 전 준비 복사본은014600Z checkpoint에 있으며 tier:null과 실제 선택을 보존한다.

## 브라우저 선택 차이와 직접 보충

Canonical 도구의 browser_scope.ROOT가 main 폴더를 가리켜 후보에만 있는 Learning 시험10파일을 놓쳤다. 실제 native 선택은13그룹/132파일이며 후보의 committed 선택은142파일이다. 일반 root pytest의 browser skip으로 이 차이를 덮지 않았다.

같은 a4139의 누락10전체파일을 `ROSY_RUN_BROWSER_TESTS=1`로 별도 원격 실행했다. AI test run `a4139efa7e-74fccd`, env `35327e86830df3ba`, freeze `906d7aca580f620b`:69수집/69PASS/skip0,132.66초, runner wait0/run135초/exit0, classifier NEW/known/flaky0. Raw SHA256은 `bc99f1ebf1d11db78c59c5a8e6ef1567c41c76814c15c73f5fe1653edb2db975`다.

독립 근거 검토가 실제 native132와 별도10의 교집합0·합집합142·누락/추가0, source/tree/argv/opt-in/raw hash와 실행 결과를 확인했다. 이 보충은 native142·native producer 편입·qualifying FULL을 뜻하지 않는다. 일반적인 후보 전용 파일 선택 결함은 미해결이다. 이번10개가 main에 생기는 것과 일반 결함 수정은 구분한다.

## 원래30 G1의 직접 실행

과거 broad suite의 mixed skip만으로23개 비브라우저 대상의 개별 통과를 추정하지 않았다. 기존 원래30대상을 그대로 같은 a4139에 직접 실행했다. AI test run `a4139efa7e-17cc90`, 동일 env/freeze, 명령은 approved remote runner의 `--sha a4139… -- ROSY_RUN_BROWSER_TESTS=1 <원래30대상> -vv -rA`다. 전체 명령·30대상·원본은 작업 공간 `ui-map/review-reports/original30-g1-a4139e/wrapper-receipt.json`과 `run-1.txt`에 있다.

실제689수집/689PASS/skip0/89warnings,669.75초, runner wait0/run682초/exit0, classifier NEW/known/flaky0. Raw SHA256은 `dae7e522b02be5893091115ca5899a35b00c9115d3b38ce90995ac1922703e02`다. 이는 원래 UI30대상의 G1이며 플랫폼 timing G1의12개 guard나 과거3ee 실행과 다르다. 최종 독립 근거 검토는 기존30대상과 순서 일치, 실제 PASSED node689개·FAILED/SKIPPED/ERROR0, 모든30대상에서 실제 통과를 확인했다. 비브라우저23대상의480개와 브라우저7대상의209개가689개를 구성하며 다른 실행과 합산하지 않는다. 실제 main·이벤트·종료 원본·20개 producer와14개 재사용 결속도 독립 대조 GO다.

## 판정의 한계

Pixel 모바일 조작부의 첫 viewport 아래 위치, SIM320의 현재/초점 항목 일부 잘림과 수동 가로 이동, Cell 사건의 첫 viewport 아래 full-page 관찰 등 기존 제한을 유지한다. 실제 스크롤 상호작용·자동 전체 노출·실카메라 품질·미촬영 조건을 새로 승인하지 않는다. 촬영과 mock HTTP의 거절 경로를 실물 안전 수용으로 바꾸지 않는다.

GitHub 공개 main/CI/게시용 적격 FULL, Release/배포, 모델 평가, 실물·운영 수용은 이 로컬 UI 목표와 별도다. 기존 accepted-main backend 사건 설명의 frameless 대기열 문제도 해결된 UI 결과로 바꾸지 않는다.

CE: 미해결 — canonical ROOT 선택 결함과 기존 backend 후속은 조사/검증 범위를 명시한 작업 기록으로 남겼으며 해결 교훈으로 쓰지 않았다. Pixel 탐색 대기 보완은 실제 trace·최소 단언·전체94개 회귀와 기존 준비 상태 지침이 판단을 보존하므로 별도 중복 교훈은 추가하지 않았다.
