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

## 2026-10-19 · uncommitted · D-806 Learning 표시 이름 게시

- 변경: 기존 검수·자료·학습·계정 화면과 오프라인 산출물의 표시 이름을 Rosy Learning으로 맞췄다. 원격 main에 없는 카메라 화면은 추가하지 않는다.
- 증거: 원래 구현과 로컬 착지 검증은 보존한다. 이 게시 head는 별도 원격 검사·독립 검토·CI로 확인한다.
- gate 변화: 없음. 이 기록은 운영 배포나 장치 수용의 증거가 아니다.

## 2026-10-20 · 1bcd83ba3a · Legacy 937 Account boundary
- 변경: 기존 별도 검수 웹의 HTTP 앞단에 D-757 개인 세션·project 권한·보호 감사 원장을 적용하고 D-809로 보존 경계를 기록했다. 운영 검수 파일을 변경하지 않았다.
- 증거: `1bcd83ba3a` 원격 합성 시험 35 passed, known_failures NEW 0. 최종 통합 SHA·게시 검사·실제 HTTPS/사용자 수용은 별도다.
- gate 변화: None. SOURCE and remote synthetic tests only; installation and user/device/field acceptance remain separate.

## 2026-10-21 · uncommitted · SIM 화면 연결 전 검수 저장 코드 분리

- 변경: ReviewStore·Conflict를 review_store.py로 옮기고 review_app의 기존 import를 유지했다. HTTP 서버는 471행, 저장 코드는 300행이며 크기 ratchet의 과거 예외를 제거했다. 서명된 학습 payload가 새 필수 모듈을 빠뜨리지 않게 source 필수 목록을 연결했다.
- 증거: 기존 클래스와 이동 후 클래스의 AST가 동일하다. 원격에서 재노출 회귀의 모듈 부재 실패와 불완전 payload의 누락 거절 부재를 먼저 확인했다. GREEN·전체 영향 검사는 최종 커밋에 대해 별도 기록한다.
- gate 변화: 없음. 기존 인간 승인·검수 자료·실행 제어를 바꾸지 않으며 새 SIM 기능·SDK 실행·호스트 배포는 아직 없다.

## 2026-10-21 · uncommitted · 공통 SIM 웹 연결

- 변경: 기존 /learning에 SIM 진입과 조회·관리 권한별 조건 확인/실행/중지·같은 요청 재전송·새 run 재실행을 추가했다. 고정 로컬 JSON subprocess가 CLI와 같은 run 실행기를 사용하고 외부 모듈/SDK를 웹에 import하지 않는다. signed payload의 필수 모듈·정적 파일과 로컬 HTTP 문서를 연결했다.
- 증거: 주입 경계 부재로 원격5실패 RED를 확인했다. 구현 후 HTTP/기존 계정/검수 회귀가 통과했다. 추가 명시적 Chromium 시험에서 공통 셸 배치 실패를 재현해 기존 rail·pathbar와 모바일 표시를 맞췄다. 실제 SDK·기존 서비스 rollout은 아직 미실행이다.
- gate 변화: 없음. 기존 인간 라벨·학습 제어·OMX 장치 권한을 변경하지 않는다.

## 2026-10-21 · uncommitted · SIM 실제 연결 경계 수정

- 변경: private workspace 설정에 binding 전체 SHA-256을 추가하고 controller/worker에서도 같은 바이트를 검증한다. 모델 PC에서 XDG_RUNTIME_DIR 없이 user bus 주소로 접근하는 경우를 재현해 고정 subprocess에 해당 운영 환경만 전달한다. GPU 준비가 다시 거절되면 이전 ready 상태를 버린다.
- 증거: 독립 검토의 binding 교체를 원격 RED2실패→GREEN477 PASS/1 SKIP로 검증했다. 실제 격리 웹에서 CLI run 조회·동일 요청·새 run의 CLI 회수와 private runtime 제외를 확인했다. production 서비스·실제 Account 로그인·기존 사람 라벨은 수정하지 않았다.
- gate 변화: 웹/CLI 교차 연결의 부분 수용이다. 실제 GPU 무점유 종료·stop 수용은 별도다.

## 2026-10-21 · uncommitted · 학습 화면 구조 정리

- 변경: 객체·픽셀 검수의 최종 배치를 HTML에 직접 적고 app.js·pixels.js의 DOM 이동 20여 건과 CSS `order` 재배열을 지웠다(좁은 폭의 픽셀 도구 이동만 남김). 테마 select와 페이지별 저장 코드 6벌을 공용 `[data-theme-cycle]` 아이콘 단추로 바꿨다. 계정 화면을 같은 셸·레일에 넣고, 입력칸처럼 그려지던 `<button class="ui-field">`를 `ui-button`으로 바꿨다. 버튼 글자에 붙은 단축키는 aria-keyshortcuts·툴팁으로, 세 번 반복되던 단축키 설명은 `?` 한 곳으로 모았다. 없는 아이콘 이름 `reload`를 `refresh`로 고쳤다.
- 증거: 정적 점검(중복 id 0, 미등록 아이콘 0, 원시 button 0). pytest·브라우저 검사는 원격 시험 PC에서 별도 기록한다.
- gate 변화: 없음. 검수 결정·저장 API·승인 규칙은 바뀌지 않는다.

## 2026-10-21 · uncommitted · 화면 사진 검토 후 학습 화면 다듬기

- 변경: 시험 PC에서 학습 화면 8개를 두 테마·두 폭으로 찍어 본 결함을 고쳤다. 사유가 붙은 비활성 단추가 아이콘·이름까지 세로로 쌓이던 공용 규칙을 한 줄+사유 아래 줄로 바꿨다. 폰 폭의 `다음 대기` 뒤 `N` 글자, 기능 검색 단추 이름의 `· Ctrl+K`를 지웠다(툴팁에 남김). 픽셀 검수 새로고침을 맨 아래에서 제목 줄로, 도구 칸을 14rem으로 넓혔다. 작업 목록 머리의 두 링크를 오른쪽에 묶고 화살표를 맞췄다. 카메라 맞춤은 기준·사진이 없으면 빈 캔버스를 숨기고 겹치기 슬라이더 폭을 줄였다. SIM 입력은 공용 폼 배치, 단추는 공용 아이콘이다. 파일 선택 단추는 공용 조용한 단추 얼굴이다.
- 증거: 시험 PC 캡처(전·후)와 정적 점검. 원격 pytest는 별도 기록한다.
- gate 변화: 없음.

## 2026-10-21 · fa16d35617 · 학습 앱 로그인을 Rosy Account 하나로

- 변경: 학습 앱의 자체 아이디·비밀번호 로그인(`POST /api/accounts/login`)과 HF OAuth 로그인을 HTTP에서 뺐다. `--collaboration` 설정은 `account_client_file`이 없으면 시작을 거절한다(D-757). Account에서 `learning.*` 권한을 받은 사용자는 학습 설정의 초대(`users`/`account_subjects`) 없이 들어온다. 이름만 같은 기존 학습 신원은 넘겨받지 않는다. 학습 권한 없이 로그인한 사용자는 401 대신 403과 권한 요청 안내를 받아 로그인 반복에 빠지지 않는다. `/accounts`의 로그인 칸은 Rosy Account 로그인 링크다. OAuth 연결 요청도 `X-Pinky-Token`을 요구한다.
- 증거: 원격 pytest는 별도 기록한다.
- gate 변화: 없음.

## 2026-10-22 · 7ef2366474 · 학습 계정의 비밀번호·HF 로그인 잔재 삭제와 공통 확인 대화상자

- 변경: Rosy Account 단일 로그인(D-757) 뒤 남은 학습 쪽 scrypt 해시, `login()`과 시도 제한, `hash-password` 명령, HF `login_subject`, 호출 없는 `link_subject`/`unlink_subject`, OAuth `login` 목적을 지웠다. HF OAuth는 `link`·`manage`만 남고, 검증된 HF 신원은 여전히 한 사람에게만 묶인다. 시험은 비밀번호 대신 `sign_in` 도우미로 세션을 만든다. 연결 해제 확인은 브라우저 `confirm()` 대신 공통 `confirmIrreversible` 대화상자다(4ce4d054c1).
- 증거: 원격 pytest는 착지 기록에 남긴다.
- gate 변화: 없음.

## 2026-10-22 · aa784c548f · fix: Rosy Account 로그인 실패의 재시도

- 변경: 잘못되거나 만료된 callback과 인증 연결 장애는 흐름 쿠키를 지우고 계정 복구 화면으로 보낸다. callback 오류·프로젝트 권한 거부 뒤 자동 재로그인 반복을 막고 Rosy Account 로그인·상태 재확인 동작을 제공한다. 연속 장애에서도 재시도 버튼을 유지하며 일시적 장애로 기존 사용자나 입력을 로그아웃시키지 않는다.
- 증거: f2d7ea9d21의 관련 원격 API 회귀 49개와 로그인·계정 Chromium 7개 통과. 반복 장애 버튼 소실은 별도 Chromium red로 재현 후 수정했다. 독립 검토의 해당 지적은 해소됐으며 최종 main 병합 후 실행은 착지 기록에 둔다.
- gate 변화: 실제 사용자 권한 부여·모델 학습·검수 원본 변경·운영 배포는 수행하지 않았다.

## 2026-10-22 · fd889ea429 · 공통 로봇·과제 학습 흐름 검증

- 변경: 프로젝트별 불변 로봇·과제 원장과 개별/협동 참여 구성을 추가했다. 과제 화면에서 자료·방법·실제 host를 선택하고 지속 경험·평가·모델 receipt까지 같은 계보를 확인한다. 과제 전달은 자료 소유권을 보존하며 자격은 전달하지 않는다. 최신 중앙 로그인·HF 연결을 보존했다.
- 증거: f5cb33bda891 원격 백엔드 2422통과·78건너뜀, Chromium 167통과. fd889ea429 Model·AI 실제 고정 CPU 환경에서 각각 ACT/HIL-SERL 합성 양팔·3카메라 자료 학습·저장·재적재 검사가 통과했다. 같은 SHA의 OAuth·Account·과제 브라우저 30통과. 각 로그의 NEW 0. 출처·한계는 [검증 기록](../../../docs/validation/learning-tasks-2026-10-22/result.md)에 명시했다.
- gate 변화: 없음. 일반 로봇 실행 어댑터, 실제 HF 동의, 공식 이미지 활성화와 실물 actor·개입·보상·초기화 수용은 별도다.

## 2026-10-22 · 08e1b34f33 · fix: HF 연결의 읽기/쓰기 분리 제거

- 변경: 일반 HF 연결에서 읽기·쓰기·저장소 관리 권한을 함께 요청하고 승인된 쓰기 권한을 보존한다. 별도의 게시 승인을 요구하던 관리 연결 분기와 두 번째 연결 버튼을 제거했다. 기존 읽기 전용 연결에는 재연결 동작을 제공한다.
- 증거: 5f298be9a3의 새 회귀 3개로 기존 실패를 재현했다. 08e1b34f33 원격 Chromium 1440/320 재연결·로그인·토큰·저장소 회귀 42 passed, 0 skipped, known_failures NEW 0. 독립 검토에서 발견한 중첩 pending 문제를 수정하고 요청·화면 이동을 검증했다.
- gate 변화: 공급자 권한·소유권·세션 검증은 유지한다. 운영 4개 서비스에는 OAuth 설정·HF 연결이 없으므로 실제 HF 동의·쓰기 성공은 별도 확인한다.

## 2026-10-22 · 18f0277fba · CI의 구형 pytest 초기화 충돌 수정

- 변경: preview와 과제 회귀의 보조 함수 이름을 구형 nose 초기화 이름과 구분했다. fixture 내용·실제 검사·기존 CI guard는 유지한다.
- 증거: PR #151의 CI39720000886에서 구형 pytest가 setup 보조 함수를 자동 호출하는 오류를 확인했다. 18f0277fba 관련 251건과 기존 CI 의존 guard 29건이 원격에서 통과했다. 최종 PR CI는 새 head로 다시 확인한다.
- gate 변화: 없음. 이전 CI 실패를 성공으로 바꾸어 기록하지 않으며 운영·사용자·실물 수용은 별도다.

## 2026-10-22 · ff01e057a6 · fix: Learning Account callback 오류에서 로그인 복구

- 변경: 거부·연결 실패·잘못된 callback에서 고정된 계정 안내로 복귀하고 프로젝트별 flow 쿠키만 지운다. 반복 장애에도 재시도 동작을 유지한다. Rosy Account 구성에서는 중앙 로그인 링크를 제공하며, 기존 비SSO 설정의 API와 폼은 보존한다.
- 증거: c13aeb8d71 원격 집중 53개 통과. 앞선 callback 단위 검사의 project cookie fixture 누락을 수정했다. 4e18d4a956 Chromium 기존 로그인·Learning 5개 통과, Auth heading 오류 2개는 ff01e057a6에서 수정 후 2개 통과했다. 최종 SHA의 게시 검사는 별도 수행한다.
- gate 변화: 계정 원장·라벨을 수정하거나 권한을 우회하지 않았다. 운영 배포·실제 사용자의 project grant는 별도 확인한다.

## 2026-10-22 · uncommitted · 게시 소스의 원격 학습센터 회귀

- 변경: 검수 snapshot과 표시 수치를 결속하고 중앙 계정 cookie 범위를 보존했다. 운영 HTTPS 전송과 별도 학습 Python의 제한된 영상 reader를 연결했다.
- 증거: source commit 1d9bce11ac의 백엔드 전체는 2366통과·78건너뜀·새 테스트 fixture 1실패였고, source commit 1dd36577a5의 해당 전송 모음 28건이 수정 후 통과했다. 앞선 게시 UI source commit b2af171cc5의 선택 전체 Chromium은 exit 0이다. 출처별 범위와 독립 검토 수정은 [검증 기록](../../../docs/validation/learning-center-publication-port-2026-10-22/result.md)에 묶었다.
- gate 변화: 없음. 일반 로봇 identity 수용, 실제 사용자/HF 동의, 운영 이미지·서비스 배포와 실물 학습은 별도다.

## 2026-10-22 · 0f3084afcf · fix: 열람 권한 부족과 로그아웃 구분

- 변경: 인증된 세션의 view 거부는 403으로 보내 자동 재로그인 반복을 막는다. 로그아웃 표시는 공통 상태 empty를 사용한다. 독립 검토의 두 발견을 반영했다.
- 증거: 7c24149120 원격 HTTP 회귀에서 기대 403 대신 401을 재현했다. ff74f0d196 집중 54개 통과. 최신 공개 main의 관측 기능과 로그를 보존해 재정렬했으며 최종 게시 검사는 별도 수행한다.
- gate 변화: 인증·권한 검증을 유지한다. 운영 설치와 사람의 계정별 수용은 별도다.

## 2026-10-22 · uncommitted · Published-source Learning Center port

- 변경: 공개 원격 main의 검수·계정 권한 경계를 유지하며 공통 로봇·과제 Learning 진입점과 OMX 과제·입력 설정, 단계별 검수·학습 화면을 옮겼다. 카메라 기준 검증, 현재 검수 결정의 학습 계보, SIM 웹 어댑터에 필요한 소스와 회귀 시험을 함께 추가했다. SIM 실행 소스·운영 binding은 제공하지 않으며 미설정 상태에서는 실행할 수 없다.
- 증거: 옮긴 소스의 Python 구문, 브라우저 JavaScript 구문, DOM 식별자와 화면 구조를 확인했다. 이 게시 소스의 커밋된 SHA에 대한 원격 pytest·Chromium·독립 검토는 대기 중이다. 보존한 개발 브랜치의 과거 시험 결과를 이 포트의 검증 결과로 사용하지 않는다.
- gate 변화: 없음. 실제 학습 실행, 정책 배포, 장치·현장 수용은 확인하지 않았다.

## 2026-10-25 · 3130321ba9 · SIM 접촉 왕복의 결과 소비 경로 연결

- 변경: 기존 SIM HTTP·화면에서 접촉 보고서와 다섯 단계 PNG를 허용하고 MIME·크기·SHA 검사를 유지했다. 모델 검사에 고정된 완료 문구·설명을 수정하고 재실행이 선택한 run의 시나리오·seed를 복원하도록 했다.
- 증거: 새 artifact 경로 9개 RED 뒤 API·Chromium 21 PASS. 독립 검토가 발견한 시나리오 복원 누락도 데스크톱·모바일 Chromium 2개 RED로 확인했으며 최종 GREEN은 착지 기록에 남긴다.
- gate 변화: SIM 결과 조회·동일 조건 재실행 연결이다. 학습 Episode 생성·policy 승격·운영 설치·실물 수용은 추가하지 않았다. 검증된 drive 방식 교훈은 Isaac 검증 기록에서 참조한다.

## 2026-10-25 · uncommitted · 공개 Learning의 접촉 왕복 증거 연결

- 변경: 공개 화면·실행 상세 링크·평가 연결을 보존하며 접촉 보고서와 다섯 PNG의 제한된 조회와 재실행 scenario 복원을 옮겼다.
- 증거: 28cbe5dc48에서 새 경로 아홉 건의 404를 재현했고 ebc1a89c52 명시적 원격 API/Chromium 26개가 통과했다. [검증 기록](../../../docs/validation/learning-conveyor-release-2026-10-25/result.md).
- gate 변화: 없음. 최종 SHA CI·운영 조회·학습 데이터·정책 평가·실물 수용은 각각 별도 확인한다.

## 2026-10-26 · d24d1abc64 · 저장공간 브라우저 시험 용량 고정

- 변경: 합성 fixture의 free_space 관측을10 GiB로 고정하고 UI 잔여값을 검증한다. 실제 storage/data 동작은 바꾸지 않았다.
- 검증: commit d24d1abc64, 모델 호스트 디스크 점검 후 실제 opt-in 두 viewport 포함10 PASS/skip0/NEW0. 기존 MAIN-RED와 raw 로그를 보존했다.
- gate 변화: 제품·기기 gate 변화 없음. docs/validation/learning-storage-browser-capacity-2026-10-26/result.md는 합성 시험 근거이며 실제 라벨·모델 수용을 뜻하지 않는다.

## 2026-10-26 · 62173b9899 · Learning 셸 정렬

- 변경: 네 정답 화면(객체·픽셀·로봇암 시범·VLM)이 같은 레일 + 경로 줄 탭(D-542 §2)을 쓴다. 로봇암 화면 제목을 메뉴 이름 `로봇암 시범 검수`로 맞췄다. 경로 줄 제목과 본문 h2가 겹치던 홈·카메라·로봇암·과제·작업 공간은 경로 줄에 제목과 화면 동작만 두고 설명은 한 줄로 내렸다. 계정 화면도 같은 앱 바·레일·경로 줄 안에 넣었다. 화면마다 복사된 테마 select·저장 코드 11벌을 지우고 공용 `data-theme-cycle`(D-668, ui-wiring.js)을 쓴다. 본문은 가운데 정렬 대신 레일 옆에 붙여 화면을 옮겨도 왼쪽 끝이 같다.
- 증거: 로컬 Edge 캡처 1366·390에서 13개 화면 페이지 오류 없음. 원격 결과는 착지 기록에 적는다.
- gate 변화: 없음.

## 2026-10-26 · 62173b9899 · 홈 안내 중복 링크 정리와 OMX 오류 문구

- 변경: 홈의 `어떤 로봇의 어떤 과제` 칸에서 경로 줄 동작(과제 등록·SIM)과 같은 페이지 앵커를 반복하던 링크 셋을 지우고 OMX 과제 링크만 남겼다. OMX 학습 실행기 미연결 오류를 한국어로 바꿨다.
- 증거: 원격 서버 시험 8f85ca2d0f 기준 shared/web·Robot·Fleet·Pilot 471 passed/0 NEW, Learning 브라우저 2456 passed/1 NEW(왼쪽 정렬 누락, 고친 뒤 89421d5732 해당 5묶음 210 passed/0 NEW). 이 커밋은 착지 시험(land.py --tests auto)이 다시 돈다.
- gate 변화: 없음.

## 2026-10-28 · fa368fe89b · 대규모 시험 문맥의 import 경로 직렬화 복구

- 변경: crash/recovery 시험의 자식 `PYTHONPATH`를 첫 등장 순서의 고유 경로로 만든다. 모든 고유 import 경로와 기존 crash 23·9MiB 부분 파일·8MiB 검증 checkpoint·정확한 재개 offset·완료 assertion·30초 timeout은 유지한다. 생산 학습 import와 실제 데이터·라벨은 바꾸지 않는다.
- 원인/재현: 커밋 8325da055d의 전체 ROOT 문맥에서는 subprocess 실행 전 E2BIG였지만 같은 소스·환경의 단독 실행은 통과했다. d1f049dbcb는 같은 기존 경로를 2MiB 이상 누적하는 조건을 넣어 단독에서도 동일 오류 RED를 재현했다. fa368fe89b의 중복 제거 후 그 조건을 포함한 파일 전체는 원격 20 passed / 1 opt-in skipped / NEW 0이었다.
- 증거: 같은 pytest 9.2 환경 1fde7a90b47fe7fb의 RED/GREEN이며, 독립 검토가 import 우선순위·모든 고유 경로와 복구 검증 조건 보존을 확인했다. 원본 로그는 native-cell-transport 작업 기록에 연결했다. 기존 일괄 감사는 29묶음 중 ROOT 1건만 비정상이었으며 공식 착지 FULL 영수증이 아니다.
- gate 변화: 없음. 기록된 skip은 대용량 실제 실험을 실행했다는 뜻이 아니며 실물·현장·학습 승격 수용은 별도다.
- CE: 해당 없음 — 전체 문맥과 단독 결과의 차이, 재현 조건과 경계 수정의 이유를 회귀 시험·이 기록에 남겼다.

## 2026-10-28 · 5404b15e21 · 녹화·검수·변환에서 고정 HF 보관으로 인계

- 변경: 미저장 native 검수의 자료 변경·재조회·이탈을 보호하고, 선택한 저장 검수는 실패·원본 버전 변경 뒤에도 명시적 복구 전까지 원본 판단으로 자동 전환하지 않는다. 변환 상태와 오류는 4단계에 표시하며 완료 데이터 ID/revision을 학습 또는 명시적 HF 보관 준비로 넘긴다. 서버는 현재 프로젝트의 등록 데이터만 검증·별도 복사하고 원본을 보존한다. 저장 동의 버튼의 상태는 홈의 일괄 busy 해제로 덮어쓰지 않는다.
- 증거: f836d5f7e2 원격 Chromium/HTTP 16 passed, skip0, NEW0. 29046060c7의 320px 밝게·1440px 어둡게 보관/설정 회귀 9 passed, skip0. 0f76cb9a4e의 저장·필수 런타임 파일 부정 회귀 255 passed, skip0. 각 실패 재현과 최종 영향·브라우저 선택은 날짜별 검증 기록에서 분리한다.
- gate 변화: 장치·모델·현장 gate 변화 없음. 실제 HF 쓰기·정책 학습·배포는 실행하지 않았다. 보관 바이트 검증과 LeRobot reader/형식 게시·정책 수용은 별개다. CE: 해당 없음 — 판단과 거부 조건을 코드·계약·실제 Chromium 회귀에 보존했다.

## 2026-10-28 · 95b205573f · 녹화 인계의 단계·키보드 초점·오류 표시 보완

- 변경: 전체 도구임을 명시하고 잘못된 단계 강조를 없애며 내부 대상의 초점·스크롤과 view 외 query를 유지한다. 변환 폴링은 같은 결과의 DOM을 보존하고 변경 때 작업/동작 초점을 복구한다. 중지 요청 대기와 거절은 새 목록에도 유지한다. 공통 조회 오류는 숨긴 학습 단계 밖에서 표시하고 회복 시 지운다. 검수 설명·한국어 필드 이름을 연결하고 명시적 보관 링크의 도착 초점은 한 번만 준다.
- 증거: 원격 RED 7/4/1건 재현 뒤 관련 전체 회귀 16/19/17 passed, skip0, NEW0. 공식 브라우저 선택 17파일의 최초 결과는 262 passed / 1 failed였고, 기존 메뉴 이동 시험의 로딩 대기를 보강한 뒤 해당 두 파일 전체 19 passed / skip0 / NEW0. 저장 검수 캡처 2건과 오류 crop 1건도 실제 Chromium으로 재검증했다. 최종 영향 선택과 원본별 SHA는 `docs/validation/recording-handoff-ui-followup-2026-10-28/`에 분리한다.
- gate 변화: 없음. 실제 HF 쓰기·실물 녹화/행동·reader 수용·배포·merge/push는 수행하지 않았다. 앞선 전체26 시험은 이전 소스의 기록이며 새 main 통합 이후의 수용으로 재사용하지 않는다.
- CE: 해당 없음. 상태·거부·초점 경계와 동기화 판단이 코드·회귀·날짜별 검증 기록에 남는다.

## 2026-10-28 · fce9c60216 · 정적 셸 원본과 자동 갱신의 작업 문맥 보존

- 변경: 12문서의 헤더·전역 메뉴를 D-910의 정적 원본으로 모았다. 조회 오류는 회복 시 지우되 실패한 저장 오류는 유지하고 실행 갱신에서 자료 선택·초점을 보존한다.
- 증거: 날짜별 검증 기록 `docs/validation/robot-pilot-learning-ux-2026-10-28/result.md`에 RED·고정 SHA·원격 영향/브라우저 결과·독립 소스/실제 화면 검토를 구분했다. 설치 자산·라우트 회귀 fce9c60216은20 passed, skip0이다.
- gate 변화: 없음. 실제 장치·APK/ARM64 빌드·현장 수용은 별도다. CE: 해당 없음 — 기존 크기 이력 교훈을 적용하고 이번 경계의 판단을 코드·회귀·D-910에 남겼다.

## 2026-10-28 · f7eaca4b3b · 카메라 판정과 평가 조회·요청의 상태 일관성

- 변경: 입력 변경과 새 기준은 이전 판정·수치를 무효화한다. 판정 입력을 await 전에 묶고 현재 generation만 반영한다. 카메라·평가는 다시 확인과 조회/요청 오류 수명을 구분하며 최신 입력을 보존한다. 승격 자격·판정 알고리즘·라벨 owner는 바꾸지 않았다.
- 증거: 집중42 passed, 공식 영향3994 passed/601 skipped, 브라우저 선택은 교정한7번33건과 나머지392건으로425 passed/skip0/NEW0이다. 독립 검토가 최종41PNG 전체를 확인했다. 원본 SHA와 fixture 실패는 `docs/validation/learning-state-consistency-2026-10-28/result.md`에 구분한다.
- gate 변화: 없음. 실제 장치·모델·사람 라벨·승격 수용·배포·merge/push는 수행하지 않았다. CE: 해당 없음 — 상태 수명·입력·초점 경계가 코드와 회귀에 남는다.

## 2026-10-29 · eca72bf579 · feat(learning): media 영수증에 sidecar shadow 증거 수 포함

- 변경: `media_pipeline.py` 영수증(`rosy.learning.media/1`)의 각 세션 행이 sidecar의 `sidecar_rows`, `shadow_live_rows`(로봇이 녹화한 payload), `shadow_backfill_rows`(오프라인 재실행 `"backfill": true` 표시)를 센다. sidecar가 없으면 세 값 모두 null. `trainer_recordings()`와 녹화 잡의 입력은 그대로다. 배경: 녹화 시 shadow 모델이 올라가 있지 않은 세션이 대부분이라(2026-10-28 실험, 모델 PC 학습 mp4에서 shadow 증거 세션 1개) 선택 전략 재료가 있는 세션이 영수증에서 보이지 않았다.
- 증거: `test_media_pipeline.py` 12 passed(live 1·backfill 1·null payload·빈 side를 구분하는 새 시험 2건 포함), AI PC 원격 실행 exit 0, `known_failures.py` 0 NEW.
- gate 변화: 없음. 세기만 하고 판정하지 않는다. shadow_live_rows 0인 세션의 백필 여부·선택 전략 채택·로봇 녹화 절차 변경은 별개 결정이다.

## 2026-10-29 · 03d493964c · 자료·계정·작업 공간의 공용 조작과 오류 복구

- 변경: Catalog는 실제 HF 상태와 조회 실패를 표시하고 권한·목록 갱신까지 인계를 잠근다. Accounts는 선택 ID·오류·직렬 잠금·초점을 보존하며 정적/동적 버튼을 공용 부품으로 통일했다. Workspaces는 재시도·빈 상태·이전 링크 제거·조건부 초점 복구를 제공한다.
- 증거: 초기 브라우저18파일300 passed, 최종 변경 범위9파일은 교정한49건과 나머지216건으로265 passed/skip0/NEW0이다. 영향3012 passed/439 skipped. 소스·캡처·fixture 실패와 실제 초점 실패는 `docs/validation/learning-data-recovery-2026-10-28/result.md`에 구분했다. 두 테마·세 폭의 공용 버튼 표적/넘침6건도 통과했다.
- gate 변화: 없음. 실제 HF·사람 라벨·모델·장치·배포·merge/push 수용은 별도다. CE: 해당 없음 — 기존 클라이언트/guard 교훈을 적용하고 상태·잠금·초점 판단을 코드·회귀·검증 기록에 남겼다.

## 2026-10-29 · 06c40584b3 · 저장 공간의 공용 버튼과 제목 배치

- 변경: 저장 재조회·공간 추정 버튼을 공용 quiet로 이행하고 submit caller·native 유효성/Enter 배선을 유지했다. 폼 제목은 전용 행에 둔다. 기존 busy/epoch·권한·인증 취소·데이터 계산은 보존한다.
- 증거: 최종 원격 실제 HTTP/Chromium9 passed/skip0와 공식 영향2880 passed/358 skipped, 각각 NEW0. 4폭×2테마의 ready/form/error24장과 독립 화면 검토를 `docs/validation/learning-storage-controls-2026-10-29/`에 고정했다. 최초 일반 버튼8 실패와 제목 geometry2 실패 원본도 보존했다.
- gate 변화: 없음. 전체 UI·모델·실물·실제 HF·배포·착지/push/merge 수용과 구분한다.
- CE: 해당 없음 — 부품/폼/임시 증거 경로의 판단은 코드·회귀·검증 기록에 남는다.

## 2026-10-29 · 8e084f3e59 · 객체·픽셀의 공용 클래스 선택

- 변경: class-chip을 공용 segment/type=button과 명시 value attribute로 이행하고 enable·pressed·test selector를 함께 고쳤다. 화면별 painting을 제거하며 데이터 색·클래스/index·권한·저장/승인·canvas 복귀를 유지했다.
- 증거: runtime b3b265f7e8의 기존 두 Chromium 파일 전체220 passed/skip0, 최종 test-only8e의 강화32 passed·16PNG, 계약80 passed와 공식 영향2880 passed/384 skipped, 모두 NEW0. 중복 subset을 합산하지 않는다. 독립 source/화면 검토와 hash는 `docs/validation/learning-class-controls-2026-10-29/` 참조.
- gate 변화: 없음. 실물·실제 라벨·전체 통합·native·배포/착지/push/merge 수용과 별도다.
- CE: 해당 없음 — attribute·상태·데이터 경계 판단이 코드·회귀·검증 기록에 남는다.

## 2026-10-29 · c38009ec42 · 작업 폭과 픽셀 승인 영역의 반응형 문맥

- 변경: 작업 cap과 별도 padding을 기존 inset 토큰으로 정리했다. pixel 승인 영역은 같은 DOM으로 compact 도구 뒤/wide 원위치를 왕복하며 체크값·초점을 보존한다. 초점 대상의 scroll margin은 appbar 높이를 반영한다. h3 전용 행·클래스/라벨·승인·저장·비동기 수명은 유지한다.
- 증거: 기존 폭/배치 RED5fail3pass 뒤425의 실제8pass/0skip·20PNG 검토. 좌표만으로 놓친 sticky header 가림은 실제 hit-test로 찾아 수정했다. 이후 도구 리본의 top12 문제를 두 테마2RED로 추가 확인했고 c380에서 공용 리본 top을 appbar/space 토큰으로 통일했다. 마지막 GREEN/캡처는 현재 대기이며 완료로 세지 않는다.
- gate 변화: 없음. 실제 사람 정답·승인·학습/HF 쓰기·실물·배포 수용이 아니다. docs/validation/platform-ui-integration-2026-10-29/result.md 참조. CE: 해당 없음 — 기존 clipping 교훈과 회귀로 원인·해결/미완료를 구분한다.

## 2026-10-29 · 66e86cb0fb · Pilot 로컬 복구와 Learning 검수 대기 연결

- 변경: 네트워크 없이 기존 Pilot 원본을 검증·변환하고, 기존 PNG/video 준비기와 catalog-relative importer로 pending 입력을 만든다. 변경된 영수증·출력은 덮어쓰지 않으며 중단된 변환 파일을 보존한다. 실제 수신·로컬 처리·사람 승인을 구분한다.
- 증거: 최종 소스의 모델 PC pinned raw/실제 FFmpeg 집중 시험 55 passed/1 opt-in skipped, 기존 녹화의 별도 검수 작업 공간 등록 시험 1 passed(19장 pending, 재실행 추가 0장). 전체 영향 선택과 RED/검토 근거는 `docs/validation/pilot-learning-collection-2026-10-29/result.md`에 기록한다.
- gate 변화: 없음. 운영 검수 DB·사람 정답·학습·모델 활성화·실물 동작은 변경하지 않았다. 새 로봇 녹화·실제 서비스 설치·착지/push는 별도다.
- CE: 해당 없음 — 복구·무결성·중복 방지 판단은 코드·회귀·운영 문서에 남는다. 로봇 접속 실패는 해결된 사실로 기록하지 않는다.
- 후속 검증: d2d68c3346의 공식 affected 전체 13,602 passed/1,285 skipped/NEW 0, 실제 기존 녹화와 pinned raw 집중 88 passed/skip0/NEW 0. 생산 코드는 66e86cb0fb와 같으며, 중간 전체 회귀의 OMX 합성 시계 실패 두 건은 기존 시계 fixture를 공유해 보완했다. 원본 실패·대조·취소·skip은 검증 정본에 보존했다.
