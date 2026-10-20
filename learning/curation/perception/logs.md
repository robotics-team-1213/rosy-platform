# perception_curation verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

2026-10-11: D-663 semantic 보존/검증과 새 road_surface_v1 classes를 추가했다. 6353771b7 원격 builder/export/intake 관련 회귀 terminal exit 0, NEW 0. 실제 road_surface 독립 검수와 승인·새 dataset publication은 미완료다.

## 2026-10-12 · 5acb174a1 · fix(learning): 모바일 검수 헤더의 작업 영역 확보

- 변경: 320px 헤더에서 브랜드·현재 작업·화면 설정을 첫 줄, 네 화면 탐색을 둘째 줄로 배치한다. 픽셀 화면의 화면 설정도 같은 클래스를 사용한다. 본문의 검수 수정·승인·자료 준비·결과와 복구 경로는 유지한다.
- 증거: main 629cb923d의 Learning 320×568 원격 Chromium에서 헤더 145px로 첫 화면 20% 예산 초과를 재현했다. 기존 높이·넘침 검사에 제목/설정 비겹침과 탐색 최소 누름면 검사를 추가했다. 수정된 커밋의 적정 자원 통합 원격 회귀와 캡처를 별도 기록한다.
- gate 변화: SOURCE 개선이며 새 설치본·사람 작업 검토·모델 승격·장치 수용은 이 변경으로 입증하지 않는다.

## 2026-10-12 · bbc523dc6 · uiux: 전체 활성 표면 통합 검증

- 변경: 기존 역할별 헤더와 본문 흐름을 검토하고 Cell 미구성 복구, Pilot 상태 근거와 연결 순서, Robot 재시도/권한 판독, Learning 작은 헤더, Android 함께 조종 안내를 통합했다.
- 증거: 적정 자원 원격 통합 342 passed, 계약·문서 64 passed, 작은 헤더/Cell 캡처 9 passed, Robot/Pilot 단계별 176/27/3/8/3 passed, 각 known_failures NEW 0. Android 106 tests와 APK 빌드 통과. 변경 후 캡처와 기존 설치본 Fleet 8 화면 조합의 직접 검토를 docs/validation/all-ui-workflows-2026-10-12/result.md에 구분해 기록했다.
- gate 변화: SOURCE·원격 회귀·변경 후 렌더링 근거다. 기존 설치본 확인은 새 변경의 배포 증거가 아니다. 새 main 착지·push·CI·서명 설치 및 실물 장치/현장 수용은 별도다.
2026-10-12: `reclaim.py`는 검증된 학습 영상 또는 검증된 compact bag이 있는 raw 세션만 `--apply`로 지운다. b7dc4f511의 `test/learning/perception/test_reclaim.py`를 모델 PC에서 실행해 10 passed, `known_failures.py` 0 NEW. 이 PC의 9.4 GB raw는 아직 지우지 않았다.

2026-10-12: `media_pipeline.py`가 학습 잡 앞에 scan, video, verify, reclaim, receipt 단계를 둔다. 027013563의 media/reclaim/recording_job 시험 39 passed, `known_failures.py` 0 NEW. 이 PC 원본에 대한 dry-run 영수증은 trainable 10, applied false다. raw는 지우지 않았다.

2026-10-12: 같은 경로에 `--apply`를 실행했다. 영수증은 trainable 10, applied true, raw_state removed 10이다. 학습 mp4 22개는 그대로고, `.compact` 두 폴더(8kcn 58.9 MB, 9dfk 30.7 MB)만 raw 아래에 남았다.

2026-10-12: e15b44f5d는 영상이 확인되면 raw가 이미 없는 `.compact`도 `--apply`로 지운다. `test_reclaim.py`와 `test_media_pipeline.py` 21 passed (`X:\DevTemp\reclaim-compact\run-1.txt`). 같은 경로 영수증은 sessions 0, applied true, compact_state removed 2(8kcn, 9dfk)다. 2026-09-28 upright 검증 영상 두 개(640×480)는 그대로 두었다.

2026-10-12: D-681 source `c7afe628ca`는 선택적 model feedback export를 기존 녹화 사건에 정확한 robot/case·content hash로 연결한다. 기존 bind/schema1과 검수 정답은 유지하며 모델 근거는 UNREVIEWED다. 실제 export→binder·CLI·한글 해시·비용/종결 무결성·크기/폴더 경계의 관련 원격 87 passed, exit 0, NEW 0. 경로는 `docs/plans/2026-10-12-model-improvement-feedback.md`; 실제 현장 데이터·학습·품질·승격은 수행하지 않았다.

## 2026-10-13 · uncommitted · feat(learning): 학습 검수 앱 바와 탐색 레일 (D-741 조각 12)

- 변경: 학습 검수 네 문서의 머리를 앱 바(R 심볼 `Learning`, 화면 표시 선택)로 줄이고, 네 화면 탭을 공용 탐색 레일(`/common/app-shell.css`, `data-seats="rail"`, 짧은 이름 목록·객체·픽셀·자료, 전체 이름은 `aria-label`)로, 쪽 제목 `<h1>`을 본문 위 경로 줄로 옮겼다. `app.css`의 머리 탭 배치 규칙은 지웠고 사진 띠·캔버스·inspector 배치는 그대로다.
- 증거: 소스 시험 `test_review_app.py::test_four_documents_share_the_app_bar_and_the_screen_rail`을 더했고 `test_review_flow_browser.py`의 머리 위치 단언 셋을 새 자리로 고쳤다. 원격 결과는 착지 보고에 적는다.
- gate 변화: 없음. 브라우저 시험은 원격에서 돌지 않아 CI 대기이고, 화면 렌더·G2·G3는 없다. 브랜치 `feat/review-app-bar`.

## 2026-10-13 · f59f1b209 · test(web): 학습 검수 앱 바 소스 시험의 자리와 원격 결과 (D-741 조각 12)

- 변경: 위 항목의 소스 시험을 `shared/web/test/test_app_shell_seats.py::test_review_documents_share_the_app_bar_and_the_screen_rail`로 옮겼다. `test/learning/perception`은 main(10581c1ce)에서도 원격 수집이 `control.sensing.perception` import로 멈춘다.
- 증거: 원격 `shared/web/test` 286 passed, 49 skipped, NEW 0 (`X:/DevTemp/review-app-bar/shared-web.txt`). `test/architecture`의 3 실패(fleet 줄 수 판정, vision 폴더 이름 둘)는 깨끗한 main에서도 같다(`X:/DevTemp/main-check/arch-main.txt`).
- gate 변화: 없음. `test_review_app.py`와 브라우저 시험은 확인 못 함.

## 2026-10-14 · 27b3b81da6 · feat: 공동 학습 계정과 HF 가져오기

- 변경: D-755 사용자·프로젝트 권한, 암호화된 복수 HF 연결, PKCE/OIDC 로그인, 고정 commit 자료 가져오기·취소·재시도와 계정 UI를 연결했다. 인증된 검수자 이력을 남기며 기존 승인 wire를 유지한다.
- 증거: 해당 HEAD의 모델 PC 원격 회귀 135 passed, known_failures 0 NEW. Chromium 1440/320px에서 두 계정 연결·선택·고정 SHA/해시 가져오기·로그아웃 철회를 검증했다. OAuth는 서명된 모의 공급자 HTTP 통합시험이다.
- gate 변화: SOURCE와 모의 공급자 통합 검증이다. 실제 OAuth 앱 미등록으로 외부 로그인·운영 활성화는 미검증이다. 가져온 자료는 pending_curation이며 권리·라벨·시간 정렬과 실제 학습 수용을 자동 승인하지 않는다.

## 2026-10-14 · 52011a517e · fix: 공동 계정 권한 표시와 세션 복구

- 변경: 연결·해제와 가져오기 제어를 현재 권한·소유자에 맞춰 표시한다. 세션 철회 시 신원·목록·입력 비밀을 지우고 재로그인하며 서버 일시 오류는 구분한다. OAuth callback 설정 오류는 workspace 바인딩 전에 거부한다.
- 증거: 수정 전 원격 재현 5 NEW, 수정 후 계정·OAuth·가져오기·HTTP·Chromium 회귀 55 passed, known_failures 0 NEW. 모바일에서 viewer/bob 전환, 타인의 프로젝트 연결·작업 제어 제한, 서버 503 복구, 세션 철회·재로그인을 확인했다.
- gate 변화: SOURCE와 격리 통합시험 보완이다. 실제 HF 앱 등록·운영 배포·실제 학습 수용은 별도이며 이 변경으로 활성화하지 않는다.

## 2026-10-14 · uncommitted · fix: 계정 이용 확인 체크박스 공용 부품 적용

- 변경: accounts.html의 내부 이용·팀 이용 확인에 ui-field와 label.ui-check를 적용했다. 입력 ID·required·이벤트 의미는 유지한다.
- 증거: CI 38435850880 core-domain에서 test_product_fields_carry_the_shared_field_class 실패를 확인했다. 기존 공용 필드 계약 시험으로 재검증한다.
- gate 변화: 없음. 실제 HF 계정·실물 활성화는 별도다.

## 2026-10-14 · 7e2ecdaea · feat: 학습 수집 저장 현황과 공간 점검

- 변경: 등록된 프로젝트 폴더의 논리·inode 중복 제외·할당 용량, 미완료 이름의 파일, 전송 대기량, 여유 공간과 일별 증가 추정을 학습 UI에 연결했다. 로컬 다운로드·staging·변환과 여유분, 유효기간이 있는 수동 원격 한도를 별도로 점검한다. 원본은 읽기만 하며 공간을 예약하거나 전송하지 않는다.
- 증거: 격리된 모델 PC HTTP·Chromium 1440/320px와 기존 검수 회귀 229 passed, 권한 철회 뒤 지연 응답 방지 보완 후 집중 시험 10 passed, 각각 known_failures 0 NEW. 파일 해시 보존, root 링크 교체 차단, 권한·프로젝트 경계, 부족·미확인·서버 오류 복구를 확인했다. 독립 코드 검토의 응답 경쟁 문제를 수정하고 재검토했다.
- gate 변화: SOURCE와 격리 통합시험 근거다. 실제 수집 폴더 설정·운영 배포·HF 원격 잔여량·업로드·실제 학습은 확인하지 않았다. 날짜별 이력이 부족하면 증가량은 미확인이며 사전 점검은 실행 중 공간 보장이 아니다.

## 2026-10-14 · d6751f094 · feat: 대용량 가져오기 재개와 실행 복구

- 변경: 고정 provider SHA-256과 영속 체크포인트로 부분 재개하고, 강제 종료 tail·Range 전체 응답·손상은 검증 후 처리한다. 같은 imports root의 OS 실행 잠금과 SQLite 트랜잭션, 실제 잔여량 공간 점검·private 한도 설정을 연결했다. UI는 파일별 진행·실패 이유·펼침/초점을 유지하고 HTTP 취소 직후 재시도를 기존 실행 종료 뒤 이어간다.
- 증거: 초기 실패 12건과 HTTP 재시도 queued 고착 1건을 원격 재현했다. 수정 후 HTTP·Chromium 1440/320px·프로세스 강제 종료·가져오기 회귀 43 passed, known_failures 0 NEW. 모델 PC 합성 9GiB는 4MiB에서 재개·전체 SHA readback 통과, 추가 RSS 2112KiB. 반복 fixture의 할당량 307683328bytes와 13.83초는 실제 영상/네트워크 처리량 근거가 아니다. 독립 검토의 5개 문제를 수정하고 재검토했다.
- gate 변화: SOURCE와 격리 전송 복구 근거다. 실제 HF 계정 전송·운영 한도 상향·배포·자료 품질·학습/장치 수용은 활성화하지 않았다. 다른 imports root나 외부 앱의 디스크 쓰기를 물리적으로 예약하지 않는다.

## 2026-10-14 · 3788d7696 · feat: Rosy Account 통합 로그인과 권한 검증 (D-757)
- 변경: 중앙 계정 저장소, PKCE, 세션 갱신과 회수, 앱별 권한 검증을 연결했다. 상세 계약과 범위는 Account completion plan과 protocol에 기록했다.
- 증거: 실제 API, SQLite, HTTPS Chromium 통합 10개 통과. 권한 회수 후 열린 WS가 15초 이내 종료됨을 검증했다. 원격 로그는 X: account-pipeline--063948 세션에 보관한다.
- gate 변화: SOURCE와 원격 시험 증거만 추가. CI, 배포, 실제 Android app-link와 현장 사용자 수용은 별도다.

## 2026-10-14 · uncommitted · feat: Hugging Face 연결로 비공개 저장소 관리

- 변경: D-765. 저장된 PAT·OAuth 연결의 기록된 범위와 `learning.publish`로 비공개 데이터셋·모델 저장소를 조회·생성·삭제한다. 읽기 연결과 가져오기는 유지한다. 파일 업로드와 Spaces는 포함하지 않는다.
- 증거: 원격 pytest와 `known_failures` 비교는 이 커밋 뒤에 기록한다.
- gate 변화: 없음. 실제 Hugging Face 계정 수용, 파일 업로드, 운영 배포는 이 변경으로 활성화하지 않는다.

## 2026-10-14 · d685e1351 · test: Hugging Face 비공개 저장소 관리 원격 시험

- 변경: 없음. D-765 구현 커밋 d685e1351의 시험 기록만 추가한다.
- 증거: 모델 PC rosy@100.98.162.71에서 d685e1351 원격 pytest 53 passed, known_failures 0 NEW (`X:\DevTemp\hf-repo-manage\run-1.txt`). 시험 PC 셋 모두 여유 메모리 6 GB 아래여서 기준 미달이지만 닿는 호스트로 실행했다.
- gate 변화: 없음.


## 2026-10-16 · uncommitted · Learning 업무 이름과 개발 표면 구분

- 변경: Learning의 검수 업무·표시 이름과 개발 표면의 제목 범위 규칙을 대조했다. 독립 앱 등록 없이 D-339의 개발 범위 제목을 유지한다. 검수·승인·export·학습 owner의 실행 의미도 유지한다.
- 증거: `docs/validation/app-role-clarity-2026-10-16/result.md`. 최종 리뷰 회귀와 affected 시험은 실행 기록에서 확인한다.
- gate 변화: 없음. main 착지·push·배포·새 DEVICE/FIELD 시험 없음.

## 2026-10-17 · eab1d0fb1 · 픽셀 사진을 AI 참고 패널보다 먼저 배치

- 변경: AI 참고 패널을 사진 위로 재이동하던 한 줄을 제거해 원래 사진 아래 배치를 유지했다. 라벨·마스크·승인 쓰기 경로는 유지한다.
- 증거: JavaScript 구문·차이 공백 검사와 독립 계약 검토 통과. 현재 시험 PC의 SSH 연결 시간 초과로 원격 브라우저 검증은 대기 중이다. docs/validation/remaining-browser-regressions-2026-10-17/result.md.
- gate 변화: 없음. 기존 실패 항목 유지. 실제 원본·사람 라벨·DEVICE/FIELD 수용은 이번 수정으로 증명하지 않는다.

## 2026-10-17 · uncommitted · 픽셀 AI 실행 패널을 사진 아래로 이동

- 변경: 원격 재검증에서 사진 두 항목이 여전히 실패했고 canvas y=539.98을 확인했다. 동적으로 생성되는 AI 실행 패널도 상태줄 다음에 붙고 있어, 사진 아래 AI 참고 패널 다음으로 옮겼다.
- 증거: `fcf3499fc7` 원격 focused 10 passed / 2 known failed 및 단독 보정 표시 1 passed, skip 없음. 수정 뒤 브라우저 검증은 다음 커밋에서 재실행한다. `C:/DevTemp/browser-regressions/recheck-20261017T051307Z/`.
- gate 변화: 없음. 라벨·초안·승인 동작은 유지하며 기존 실패 항목은 실제 green 전까지 남긴다.

## 2026-10-17 · uncommitted · 픽셀 검수 주체 요약을 현재 결과에 연결

- 변경: 모델 PC의 합성 상태 캡처와 DOM 좌표로 사진 위 검수 주체·이력 링크 두 줄을 확인했다. 픽셀 요약과 링크는 사진 아래 현재 결과 다음에 놓고 객체 화면의 위치는 유지한다.
- 증거: `a10c699f9` 원격 16 passed / 2 known failed 및 단독 보정 표시 1 passed, skip 없음. canvas y=344.98, 짧은 화면 하단 656.98로 두 기존 배치 검사가 아직 실패했다. 원격 캡처·좌표는 `C:/DevTemp/browser-regressions/recheck-20261017T051307Z/layout/`.
- gate 변화: 없음. 검수 주체·이력 데이터와 라벨 쓰기는 유지한다. 합성 캡처는 실제 사람 검수나 모델 정확도의 증거가 아니다.

## 2026-10-17 · uncommitted · 검수 주체 요약을 픽셀 결정·이력 영역에 배치

- 변경: 사진 두 기존 실패는 해소됐지만 결과와 편집 도구 사이의 검수 주체 요약이 전화 폭 도구 간격을 늘렸다. 요약을 오른쪽 결정 열의 실제 검수 이력 바로 앞으로 옮겨 사진·편집 도구의 연속성을 유지한다.
- 증거: `39b9305543` 원격 17 passed / 2 NEW 및 단독 보정 표시 1 passed, skip 없음. 새 실패는 390·320 폭 사진-도구 간격이었다. 기존 다섯 실패는 이번 회차에서 통과했으나 목록 해제는 전체 focused green 이후 진행한다.
- gate 변화: 없음. 앞선 실패와 캡처는 보존하며 새 실패를 기준선에 추가하지 않는다.

## 2026-10-17 · 0e8ba72832 · 사진 배치와 전화 편집 도구 재검증 통과

- 변경: 픽셀 사진·현재 결과·편집 도구를 먼저 두고 AI 실행과 검수 주체 요약은 아래 참고·결정 영역에 둔다.
- 증거: 원격 focused 19 passed, skip 0, NEW 0. 기존 사진 두 실패와 전화 도구 간격·검수 이력·AI 초기화·원본 보존을 함께 확인하고 최종 합성 캡처 세 폭을 직접 읽었다. docs/validation/remaining-browser-regressions-verified-2026-10-17/result.md.
- gate 변화: 없음. 사람 라벨·모델 정확도·실측·장치 수용은 별도다.

## 2026-10-19 · uncommitted · D-806 앱 표시 이름과 현재 역할 정합

- 변경: 객체·픽셀·자료·학습·카메라·계정 화면 제목을 Rosy Learning — 화면으로 맞췄다. 계정 화면도 Learning 앱 바를 쓴다. 학습·검수·사람 라벨·실행 권한은 유지한다.
- 증거: 제목 회귀 검사의 수정 전 원격 실행은 2 failed로 기존 불일치를 확인했다. 수정 후 검증은 이 작업의 커밋과 외부 시험 기록으로 확인한다.
- gate 변화: 없음. 이름·문서·정적 화면 범위이며 설치·실물 실행·DEVICE/FIELD 수용을 바꾸지 않는다.

## 2026-10-19 · 9c1160981c · D-806 이름 정합 검증 완료

- 변경: 이전 Cell 안내·지도 제목을 기대하던 브라우저 검사를 승인한 이름으로 맞췄다. Games 480px·600px 검사를 추가했다.
- 증거: 구현 689cb1e968의 원격 affected 8,767 passed / 889 skipped, 관측 서비스 647 passed. Chromium 230 passed와 이전 문구 기대값 4 failed는 9c1160981c에서 수정 후 4 passed, Games 중간 폭은 989b806b34에서 2 passed. 최종 비교 NEW 0. 커밋·로그·실행 범위는 docs/validation/app-names-2026-10-19/result.md에 기록했다.
- gate 변화: 없음. main 병합·push·배포·실물 수용은 수행하지 않았다.

## 2026-10-19 · a73095ddfe · 보관된 OMX 학습 S3/S4 통합과 카메라 증거 결속

- 변경: 보관 원본2dd4d009b9의 D-792 S3 shadow 점검·S4 읽기 전용 OMX 화면과 D-794 front/wrist 읽기 별칭을 현재 main에 통합한다. 독립 검토에서 찾은 역할이 다른 기준의 적용과 첫 교정값 재사용을 수정했다. wrist 기준은 확인 자세를 요구하고, 교정값이 바뀌거나 사라지는 역할은 세션 전체를 측정 불가로 기록한다. 사람 검수·실행·승격 권한을 추가하지 않았다.
- 증거: AI 시험 PC의4e682c9bd2 focused11개 중6실패5통과로 두 문제를 재현했다. 수정a73095ddfe에서 같은11개 모두 통과, skip0. 로그는 외부 scratch rosy-worktree-reconcile/omx-intake-red-collected 및 omx-intake-green/run-1.txt. 최종 독립 소스 검토에서 남은 finding 없음. 전체 착지·브라우저 관문은 별도 수행한다.
- gate 변화: 없음. 프레임 시각별 교정 선택은 아직 없으므로 교정 변경 전의 유효한 프레임도 보수적으로 측정 불가일 수 있다. 실물 카메라 정확도·학습 품질·운영 라벨·배포는 검증하지 않았다.

## 2026-10-19 · a58e7fdaaa · 이전 검수 이력의 클래스 바인딩 경쟁 수정 이식

- 변경: 과거 이력0ef4c1bebf의 재검사를 현재 일반 importer의 잠금 안으로 옮겼다. 파일 preflight 동안 다른 import가 클래스셋을 먼저 확정하면, 거절된 YAML·프레임·결정 파일을 쓰기 전에 중단한다. 다른 검수자의 기존 바인딩과 라벨은 보존한다.
- 증거: 합성 상태를 쓰는 원격98ae70a563에서 거절된 클래스 YAML이 남는1실패를 재현했다. 수정a58e7fdaaa의 회귀·기존 review cycle·pixel draft import57개 모두 통과, skip0. 로그는 외부 scratch rosy-worktree-reconcile/review-binding-red 및 review-binding-green/run-1.txt. 승리한 import 이후 전체 DB 논리 내용과 비DB 파일 해시가 변하지 않음을 검사했다. 전체 착지 관문은 별도 수행한다.
- gate 변화: 없음. 원본 브랜치의 signed portable-catalog 파이프라인·과거13866개 이력을 병합한 것은 아니다. 운영 사람 라벨·서명 배포·실물·브라우저 수용은 검증하지 않았다.

## 2026-10-19 · 1bcc82a593 · portable catalog와 명시적 legacy 동영상 준비 이식

- 변경: 원본18b06c2172의 catalog-relative PNG/video 참조를 POSIX no-follow·같은 핸들 bounded capture로 검증하고, persistence 잠금 안에서 namespace를 재확인한다. 기존 main 클래스 바인딩 경쟁 재검사를 유지한다. 명시한 안전한 legacy session을 허용하되 canonical identity 덮어쓰기와 이미지 목적지 충돌은 거절한다. 동영상 바이트의 독립 검증·새 인간 승인·실행 권한을 만들지 않는다.
- 증거: 시험 import를 현재 ReviewStore로 보정한 commit bd097e5091의 원격 실행에서32개 실패를 재현했다. 생산 수정1bcc82a593의 기본 선택은124통과와 mcap_ros2 부재1실패였으며 이를 전체 통과로 세지 않았다. 격리된 native pinky-raw profile의 readiness가 package origin·version·closure를 확인한 뒤 같은125개를 모두 통과했다. 선택 시험에는 기존 클래스 바인딩 경쟁 회귀도 포함된다.
- 환경: 기본 MCAP control만 기존 MCAP suite와 같은 optional dependency 조건을 사용한다. 해당 코드·시험 변경의 착지는 모듈 AGENTS의 필수 raw-profile 검사 exit0/skip0을 별도로 요구한다. 환경 분리 commit db23d46516도 실제 raw125passed/skip0, NEW/known/flaky0이다. source_components 분할 알고리즘은 이식하거나 검증했다고 주장하지 않는다. 최종 로그·생성물이 담긴 HEAD도 착지 전에 raw 검사를 다시 확인한다.
- 범위: strict signed source expectation/retained proof는 별도 후속 단위다. 운영 라벨·실물·배포·학습 품질·현장 수용은 검증하지 않았다.
- gate 변화: 없음. 기본 환경의 optional MCAP 검사는 필수 raw-profile 검사 exit0/skip0을 대신하지 않는다.

## 2026-10-21 · uncommitted · SIM 화면 연결 전 검수 저장 코드 분리

- 변경: ReviewStore·Conflict를 review_store.py로 옮기고 review_app의 기존 import를 유지했다. HTTP 서버는 471행, 저장 코드는 300행이며 크기 ratchet의 과거 예외를 제거했다. 서명된 학습 payload가 새 필수 모듈을 빠뜨리지 않게 source 필수 목록을 연결했다.
- 증거: 기존 클래스와 이동 후 클래스의 AST가 동일하다. 원격에서 재노출 회귀의 모듈 부재 실패와 불완전 payload의 누락 거절 부재를 먼저 확인했다. GREEN·전체 영향 검사는 최종 커밋에 대해 별도 기록한다.
- gate 변화: 없음. 기존 인간 승인·검수 자료·실행 제어를 바꾸지 않으며 새 SIM 기능·SDK 실행·호스트 배포는 아직 없다.

## 2026-10-21 · uncommitted · 공통 SIM 웹 연결

- 변경: 기존 /learning에 SIM 진입과 조회·관리 권한별 조건 확인/실행/중지·같은 요청 재전송·새 run 재실행을 추가했다. 고정 로컬 JSON subprocess가 CLI와 같은 run 실행기를 사용하고 외부 모듈/SDK를 웹에 import하지 않는다. signed payload의 필수 모듈·정적 파일과 로컬 HTTP 문서를 연결했다.
- 증거: 주입 경계 부재로 원격5실패 RED를 확인했다. 구현 후 HTTP/기존 계정/검수 회귀가 통과했다. 추가 명시적 Chromium 시험에서 공통 셸 배치 실패를 재현해 기존 rail·pathbar와 모바일 표시를 맞췄다. 실제 SDK·기존 서비스 rollout은 아직 미실행이다.
- gate 변화: 없음. 기존 인간 라벨·학습 제어·OMX 장치 권한을 변경하지 않는다.
