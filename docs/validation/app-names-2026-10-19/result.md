# 앱 이름·역할 정리 검증

2026-10-19. 사용자 승인 명명안은 [D-806](../../adr/D-806-app-display-names-and-implemented-product-roles.md), 현재 앱·기능·서비스의 구분은 [앱 이름과 역할](../../reference/app-names-and-roles.md)을 따른다.

## 변경과 소스

- 플랫폼 작업 위치: `.worktrees/app-names`, 브랜치 `uiux/app-names`.
- 변경 전 기준: `48fdd711ae96cf394e1a43f264c35d84855cedff`.
- 실제 화면·문서·이름 메타데이터 구현: `689cb1e96893f942c0fac573b7b8e55e27330318`.
- Games 480px·600px 검사 추가: `989b806b347bd987dda1eac2265aac6d7d15d56d`.
- Cell 안내·지도 제목의 기존 브라우저 기대값 수정: `9c1160981ccb536d7e1bc6d0f8b8be11df81e19f`.
- 별도 `rosy-vault` 저장소: `chore/rosy-vault-branding`, `d7390b322dfad74db4f8de2c9cb89a05825956a4`.

플랫폼 구현 커밋 이후에는 검사와 문서만 수정했다. 아래 검증을 마지막 문서 기록 커밋 전체에 대한 CI 결과로 해석하지 않는다.

## 실행 결과

| 검사 | 소스 | 결과 |
|---|---|---|
| 제목 검사 RED | `1aaef7b894` | 2 failed. 기존 하위 화면 제목과 웹 앱 이름 메타데이터 부재를 확인 |
| affected 일반 회귀 | `689cb1e968` | **8,767 passed, 889 skipped, 38 warnings**, exit 0 |
| affected 관측 서비스 | `689cb1e968` | **647 passed**, exit 0 |
| 실제 Chromium 9개 파일 | `689cb1e968` | **230 passed, 4 failed, 2 warnings**. 아래 이전 문구 기대값만 실패 |
| Cell·지도 수정 후 Chromium | `9c1160981c` | **4 passed, 2 warnings**, exit 0 |
| Games 중간 폭 Chromium | `989b806b34` | **2 passed**, exit 0. 480px·600px 수평 넘침·정지 접근성 확인 |
| Vault·Device 전체 pytest | `d7390b322d` | **188 passed, 4 skipped, 1 warning**, exit 0 |

일반 회귀·관측 서비스·수정 후 Cell/지도·Games 중간 폭 로그는 각각 `test/known_failures.py`로 비교해 **0 new, 0 known, 0 flaky**를 확인했다. 실패 목록을 추가하거나 검사를 약화하지 않았다.

889개 skipped는 실행 통과로 세지 않았다. 일반 묶음의 선택적 브라우저 검사 전체를 활성화한 실행은 아니며, 변경한 주요 화면은 별도 Chromium 묶음으로 확인했다. 일반 로그는 개별 skip 이유를 모두 출력하지 않는다. Vault의 4개 skip은 별도 실제 Fleet 통합 환경이 필요한 검사다.

## 브라우저 실패와 수정

첫 브라우저 묶음에서 다음 4건이 이전 화면 문구를 기대했다.

- `test_cell_app_browser.py::test_cell_explains_work_and_unconfigured_service`: 이전 “레시피와 셀 문서를 준비”와 새 팔레타이징 역할 안내의 차이.
- `test_site_map_browser.py::test_view_edit_activate_and_preview_a_trip`: 1440×1000, 390×844, 320×568에서 이전 `Rosy Fleet · 현장 지도`와 새 `Rosy Fleet — 현장 지도`의 차이.

해당 기대값을 승인한 이름·역할로 맞추고 Cell의 주제 `팔레타이징 작업 준비`도 검사했다. 4건 모두 실제 Chromium으로 다시 실행해 통과했다. 초기 묶음의 exit 1은 그대로 기록하며 전체 234건을 마지막 커밋에서 재실행했다고 주장하지 않는다.

## 실행 방법과 로그

플랫폼 pytest는 개발 PC에서 실행하지 않고 `tools/remote/remote_pytest.py`가 커밋을 시험 PC로 전달했다. 일반 회귀는 AI 시험 PC, 관측 서비스·첫 Chromium·중간 폭은 모델 시험 PC, 수정 후 4건은 runner가 선택한 사이트 시험 PC의 격리된 시험 환경에서 실행했다. 각 실행은 테스트 fixture를 사용했다.

로그 루트는 개발 PC의 시스템 임시 디렉터리(`%TEMP%`)다.

| 디렉터리 | 파일·내용 |
|---|---|
| `rosy-app-names-red` | `run-1.txt`: 수정 전 제목 검사 |
| `rosy-app-names-affected` | `run-1.txt`: 일반 회귀, `run-2.txt`: 관측 서비스 |
| `rosy-app-names-browser` | `run-1.txt`: 첫 Chromium 230 passed / 4 failed |
| `rosy-app-names-browser-followup` | `run-1.txt`: 수정 후 4건 |
| `rosy-app-names-medium` | `run-1.txt`: Games 480px·600px |

완료된 로그의 SHA-256:

| 로그 | SHA-256 |
|---|---|
| `rosy-app-names-red/run-1.txt` | `93bedda4bd8dbc4b237003539667fe2ff81cf9c45a94d336a2af4377dbe0f5b5` |
| `rosy-app-names-affected/run-1.txt` | `44dd5cfbc9f28a39d73653e198c0e7a303c037bc3fa766d473c7c7079d3ea780` |
| `rosy-app-names-affected/run-2.txt` | `1c272fc6db32d14b1f7b77c1f9eb1b8c66b4970832d6c35bef1ff0d486d093f5` |
| `rosy-app-names-browser/run-1.txt` | `0ff92042f593fb75c3d369ae97008cc8b5ebb402fb98f74f92758237447b795b` |
| `rosy-app-names-browser-followup/run-1.txt` | `3e0bf918a316eff946427c9da6a64fbaa7b759f7d1e82c1a7889805a6aefe4c1` |
| `rosy-app-names-medium/run-1.txt` | `16790b00b11983e516839653d9f35b7af2780f72dedf9baf350699a1783525d8` |

영향 범위는 `rosy_harness.py affected --base 48fdd711ae96cf394e1a43f264c35d84855cedff --head 689cb1e96893f942c0fac573b7b8e55e27330318 --json`의 `mode=affected` 선택을 원격 runner의 `--affected-json -`로 전달했다. 브라우저 실행에는 `ROSY_RUN_BROWSER_TESTS=1`을 명시했다. 콘솔 인코딩 문제로 첫 RED 실행의 결과 출력이 실패했지만 로그에는 실제 pytest 2 failed가 남았고, 후속 runner는 `python -X utf8`로 실행했다.

## 검토와 범위

- 독립 읽기 전용 리뷰에서 이름·화면 소속·기존 신원·조작 순서의 수정 필요 문제를 찾지 못했다. 리뷰가 확인을 권한 Games 중간 폭은 추가 검사로 통과했다.
- 앱은 Robot·Fleet·Pilot·Cam·Learning·Games·Vault·Device로 구분한다. Cell은 Fleet의 팔레타이징 준비, Account는 공용 인증 기능, 얼굴·연결 로비는 하위 표면이다.
- URL·포트·패키지·스키마·systemd·명령·정지·안전 로직은 변경하지 않았다. native Pilot·Cam의 현재 런처 이름은 소스에서 각각 Rosy Pilot·Rosy Cam임을 확인했으며 APK는 새로 빌드하지 않았다.
- main 병합·push·배포·실물 장치 동작·양팔 DEVICE/FIELD 수용은 수행하지 않았다. 이 기록은 해당 승격 증거를 대신하지 않는다.
