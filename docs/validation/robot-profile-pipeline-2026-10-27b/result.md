# 로봇 프로필·하중 분석 파이프라인 로컬 통합 검증

2026-10-27 로컬 main에 commit `b69d9c7362bbc32b0b5b86a787aa7189a81225a0`을 fast-forward로 반영했다. 최종 직전 main인 commit `ae535f57ec` 대비 62개 커밋이며, 보존된 하중 분석 구현과 로봇별 프로필 연결을 포함한다. 도구가 출력한 103개는 최초 회차 main인 commit `fb006de2b7` 대비 수치로, 최종 fast-forward에서 새로 반영된 수와 구분한다. 외부 push·배포·실물 동작·고장 해제·자동 복구는 수행하지 않았다.

이 기록은 [앞선 구현·검증 기록](../robot-profile-pipeline-2026-10-27/result.md)의 후속 통합 결과다. 이전 날짜 기록의 결과는 수정하지 않는다.

## 반영한 동작

- 로봇/Cell을 선택하면 현재 관측 상태 뒤에 저장된 주의사항·최근 진단, 특성·이력을 보여 주고 기존 앱·대형·조치 버튼을 배치한다. 긴급 정지는 프로필 조회를 기다리지 않는다.
- 특성 JSON·주의사항·수정자·날짜와 진단을 기존 task SQLite에 저장한다. Viewer는 조회하고 이름 있는 Operator가 편집한다. DB 미구성·조회 실패·미등록·오래된 관측은 확인 불가 상태로 표시한다.
- 등록 source의 관측 자격으로만 보고서를 수집한다. 장비·owner·등록 binding·특성 digest·구성·시각을 검사하며, 중복 전송은 신선도를 갱신하지 않는다. 장비 교체 시 이전 주의사항을 새 장비의 현재 정보로 재사용하지 않는다.
- 특성 검증은 Fleet 저장과 OMX 계산이 같은 ROS-free motion 계약을 사용한다. 기존 adapter import는 유지한다. 저장된 실측 도메인을 이용한 후보 평가와 수동 진단이며, care 보고서가 동작 허가나 자동 복구 권한을 만들지 않는다.

사용 및 구성은 [장비 care 안내](../../../operations/fleet/docs/device-care.md)와 [하중 분석 안내](../../../middleware/devices/omx/adapter/docs/load-aware-motion.md)를 따른다. 편집은 설치 화면의 장비 프로필에서 수행한다.

## 커밋과 공식 병합 기록

main에서 다음 세 커밋의 ancestry를 직접 확인했다: 원본 하중 구현 commit `58b219cbef5a328a963c8650a814507173ccace2`, HTTP 증거 검증 commit `0a3bca1f98`, 최종 통합 commit `b69d9c7362bbc32b0b5b86a787aa7189a81225a0`. main의 추적 파일은 깨끗했으며 동료의 기존 미추적 문서는 보존했다.

실행 명령은 `python tools/land.py --tests auto --no-prune`다. 공식 기록은 공통 Git 디렉터리의 `rosy-land/<sha>.json`에 있으며, `<sha>`는 아래 표의 통합 commit이다.

전체 Git ID는 종류를 명시해 표에 유지하고 경로에는 placeholder를 사용했다. [기존 해시 표기 교훈](../../solutions/workflow-issues/git-ids-in-validation-records-need-the-commit-prefix-2026-10-07.md)에 따른 표기 수정이며 관측 결과·scanner·허용 목록은 변경하지 않았다.

| 기록 필드 | 값 |
|---|---|
| `sha`, `prepared_candidate` | commit `b69d9c7362bbc32b0b5b86a787aa7189a81225a0` |
| `base`, `prepared_on` | commit `ae535f57ec8770c4d2ab8c4adb2bbc7b24b856d5` |
| 최종 tier | `affected`, 선택된 pytest 호출 12개, 최종 결과 보고서 `run-4-1.txt` |
| 반영 시각 | `2026-10-27T08:17:10+00:00` |
| 기록 파일 무결성 | sha256:e2cc93120efd39d3bad1b13724c1cfb30aa3083e1b0e3d0e61c4dc3d2d407e19 |

총 4회차를 거쳤다. 과거 FULL 준비 commit `41b608c7c7` 이후 main 변경분을 재검증하는 도구 규칙과 캐시를 사용했다. 최종 회차에서도 같은 트리의 계약 검사 결과를 재사용했다. 아래 수치를 합산해 최신 커밋에서 전체 플랫폼 FULL을 새로 실행했다고 주장하지 않는다. 제한 시간으로 취소된 부분 결과는 통과로 세지 않는다.

PowerShell wrapper는 마지막에 exit 1을 반환했지만 도구의 공식 출력은 성공·main 갱신을 기록했다. 따라서 wrapper 상태만으로 판단하지 않고 공식 기록과 실제 main ancestry를 확인했다.

## 실제 실행 증거와 범위

다음 후보 검사는 모두 commit `b69d9c7362bbc32b0b5b86a787aa7189a81225a0`에 묶인다. 원격 Python 환경의 설치 입력 식별자는 `dc5e885d09c14b49`다. 로컬 pytest는 실행하지 않았다.

| 증거 | 결과와 범위 |
|---|---|
| `integration-b69-preparation/run-pre-2.txt` | `operations/fleet/test` 루트를 포함한 coalesced 명령: 7,444 통과·407 제외, 302.04초. ignore/deselect를 추가하지 않았다. 제외된 브라우저는 아래 별도 실행 증거와 구분한다. |
| `integration-b69-preparation/run-pre-1.txt` | CORE·애플리케이션 등 별도의 coalesced 명령: 4,687 통과·225 제외·5 subtests, 985.63초. 위 Fleet-root 명령과 다른 범위다. |
| `b69-profile-browser-acceptance/run-pre-10.txt` | `ROSY_RUN_BROWSER_TESTS=1`인 Cell/care/실제 pipeline 브라우저 묶음: 48 통과·0 제외, 141.86초. 실제 LoadMonitor 출력→bridge 요청→source 인증 API→SQLite→새 app/store의 DB 재개방→실제 Cell 브라우저 표시를 포함한다. 프로필 API 응답을 브라우저에서 대체하지 않는다. 데스크톱·모바일 표시와 정보/권한/신선도 시나리오를 포함한다. |
| 로컬 main Node 검사 | 저장소의 `register-console-assets.mjs`를 `--import`로 적용하고 `operations/fleet/test/web`의 모든 `*.test.mjs` 실행: 398 통과·0 실패·0 제외, exit 0. `node-final-main.txt`에 보존했다. |
| 독립 계약 delta 검토 | 최신 후보의 실제 생산자·인증·지속 binding·Cell 소비 경로와 정보 우선 순서에서 지원되는 새 중대한 지적 없음. matrix의 실제 HTTP receipt 9개와 flow 기록 3개가 보존됨을 확인했다. 시험 실행이나 실물 수용을 대신하지 않는다. |

원격/Node 원본은 저장소 밖 `%TEMP%/rosy-profile-pipeline/` 아래 위 이름의 폴더·파일에 보존했다. 공식 전체 실행 로그는 `land-main-refresh.txt`다. B69 pipeline 보고서 무결성은 sha256:85b5f45bcca83d55d07ae1be6480a7e1ddcc0ca07e6a865c48dea7456f147d1d다. 함께 보존한 gateway 로그는 그 시점의 부분 snapshot이며, 전체 실행 로그와 구분한다.

## 재실행 통과와 미해결 관측

e5 후보의 기존 Cell 준비 화면 저장 대기 검사 2건과 B69 후보의 `test_sample_browser.py::test_cell_document_preview_admission_and_terminal_read` 1건은 묶음 실행에서 실패한 뒤 공식 D-790 단독 재실행에서 통과해 `LOAD-FLAKY`로 기록됐다. B69 sample 재실행은 6.04초였다. 시험 시간·known-failure·quarantine 목록은 바꾸지 않았다.

이전 main의 station 시간초과와 위 화면 시간초과의 원인은 아직 확정하지 않았다. 후속 main/후보 통과나 단독 재실행 통과를 원인 해결로 쓰지 않는다. 추가 조사는 같은 소스·부하 조건에서 실제 대기 시간과 HTTP 저장/조회 상태를 계측해야 한다. CE: 미해결. 검증된 해결이 없으므로 해결 교훈을 만들지 않는다.

## 수용 한계와 운영 확인

브라우저 pipeline 입력과 측정 도메인은 합성이며 HTTPS 전달은 TestClient 어댑터를 사용했다. 실제 인증서, 실물 raw/radian 보정, 인증된 하중·COM·온도·전압 한계, 추가 버스 읽기 주기와 실물 추종·진동 개선 효과는 수용하지 않았다. 실물 설정에 시험 fixture 수치를 복사하지 않는다.

관측이 오래됐거나 binding이 달라지면 현재 상태를 확인 불가로 보고 등록 source와 프로필 연결을 명시적으로 다시 확인한다. 과거 진단을 현재 정상 증거로 사용하지 않는다. 특성 JSON의 `draft`/`measured` 표기나 주의사항 편집은 장치 고장 해제 또는 실행 허가가 아니다. 자동 대체 이동, 충돌/IK 검증과 최종 실행·정지·복구 권한은 이 변경의 수용 범위에 포함하지 않는다.
