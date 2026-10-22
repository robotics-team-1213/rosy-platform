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

## 2026-10-19 · uncommitted · D-806 Learning 표시 이름 게시

- 변경: 기존 검수·자료·학습·계정 화면과 오프라인 산출물의 표시 이름을 Rosy Learning으로 맞췄다. 원격 main에 없는 카메라 화면은 추가하지 않는다.
- 증거: 원래 구현과 로컬 착지 검증은 보존한다. 이 게시 head는 별도 원격 검사·독립 검토·CI로 확인한다.
- gate 변화: 없음. 이 기록은 운영 배포나 장치 수용의 증거가 아니다.


## 2026-10-20 · 1bcd83ba3a · Legacy 937 Account boundary
- 변경: 기존 별도 검수 웹의 HTTP 앞단에 D-757 개인 세션·project 권한·보호 감사 원장을 적용하고 D-809로 보존 경계를 기록했다. 운영 검수 파일을 변경하지 않았다.
- 증거: `1bcd83ba3a` 원격 합성 시험 35 passed, known_failures NEW 0. 최종 통합 SHA·게시 검사·실제 HTTPS/사용자 수용은 별도다.
- gate 변화: None. SOURCE and remote synthetic tests only; installation and user/device/field acceptance remain separate.

## 2026-10-22 · ff01e057a6 · fix: Learning Account callback 오류에서 로그인 복구

- 변경: 거부·연결 실패·잘못된 callback에서 고정된 계정 안내로 복귀하고 프로젝트별 flow 쿠키만 지운다. 반복 장애에도 재시도 동작을 유지한다. Rosy Account 구성에서는 중앙 로그인 링크를 제공하며, 기존 비SSO 설정의 API와 폼은 보존한다.
- 증거: c13aeb8d71 원격 집중 53개 통과. 앞선 callback 단위 검사의 project cookie fixture 누락을 수정했다. 4e18d4a956 Chromium 기존 로그인·Learning 5개 통과, Auth heading 오류 2개는 ff01e057a6에서 수정 후 2개 통과했다. 최종 SHA의 게시 검사는 별도 수행한다.
- gate 변화: 계정 원장·라벨을 수정하거나 권한을 우회하지 않았다. 운영 배포·실제 사용자의 project grant는 별도 확인한다.

## 2026-10-22 · 0f3084afcf · fix: 열람 권한 부족과 로그아웃 구분

- 변경: 인증된 세션의 view 거부는 403으로 보내 자동 재로그인 반복을 막는다. 로그아웃 표시는 공통 상태 empty를 사용한다. 독립 검토의 두 발견을 반영했다.
- 증거: 7c24149120 원격 HTTP 회귀에서 기대 403 대신 401을 재현했다. ff74f0d196 집중 54개 통과. 최신 공개 main의 관측 기능과 로그를 보존해 재정렬했으며 최종 게시 검사는 별도 수행한다.
- gate 변화: 인증·권한 검증을 유지한다. 운영 설치와 사람의 계정별 수용은 별도다.

## 2026-10-22 · 08e1b34f33 · fix: HF 연결의 읽기/쓰기 분리 제거

- 변경: 일반 HF 연결에서 읽기·쓰기·저장소 관리 권한을 함께 요청하고 승인된 쓰기 권한을 보존한다. 별도의 게시 승인을 요구하던 관리 연결 분기와 두 번째 연결 버튼을 제거했다. 기존 읽기 전용 연결에는 재연결 동작을 제공한다.
- 증거: 5f298be9a3의 새 회귀 3개로 기존 실패를 재현했다. 08e1b34f33 원격 Chromium 1440/320 재연결·로그인·토큰·저장소 회귀 42 passed, 0 skipped, known_failures NEW 0. 독립 검토에서 발견한 중첩 pending 문제를 수정하고 요청·화면 이동을 검증했다.
- gate 변화: 공급자 권한·소유권·세션 검증은 유지한다. 운영 4개 서비스에는 OAuth 설정·HF 연결이 없으므로 실제 HF 동의·쓰기 성공은 별도 확인한다.
## 2026-10-22 · uncommitted · Published-source Learning Center port

- 변경: 공개 원격 main의 검수·계정 권한 경계를 유지하며 공통 로봇·과제 Learning 진입점과 OMX 과제·입력 설정, 단계별 검수·학습 화면을 옮겼다. 카메라 기준 검증, 현재 검수 결정의 학습 계보, SIM 웹 어댑터에 필요한 소스와 회귀 시험을 함께 추가했다. SIM 실행 소스·운영 binding은 제공하지 않으며 미설정 상태에서는 실행할 수 없다.
- 증거: 옮긴 소스의 Python 구문, 브라우저 JavaScript 구문, DOM 식별자와 화면 구조를 확인했다. 이 게시 소스의 커밋된 SHA에 대한 원격 pytest·Chromium·독립 검토는 대기 중이다. 보존한 개발 브랜치의 과거 시험 결과를 이 포트의 검증 결과로 사용하지 않는다.
- gate 변화: 없음. 실제 학습 실행, 정책 배포, 장치·현장 수용은 확인하지 않았다.

## 2026-10-22 · uncommitted · 게시 소스의 원격 학습센터 회귀

- 변경: 검수 snapshot과 표시 수치를 결속하고 중앙 계정 cookie 범위를 보존했다. 운영 HTTPS 전송과 별도 학습 Python의 제한된 영상 reader를 연결했다.
- 증거: source commit 1d9bce11ac의 백엔드 전체는 2366통과·78건너뜀·새 테스트 fixture 1실패였고, source commit 1dd36577a5의 해당 전송 모음 28건이 수정 후 통과했다. 앞선 게시 UI source commit b2af171cc5의 선택 전체 Chromium은 exit 0이다. 출처별 범위와 독립 검토 수정은 [검증 기록](../../../docs/validation/learning-center-publication-port-2026-10-22/result.md)에 묶었다.
- gate 변화: 없음. 일반 로봇 identity 수용, 실제 사용자/HF 동의, 운영 이미지·서비스 배포와 실물 학습은 별도다.

## 2026-10-22 · fd889ea429 · 공통 로봇·과제 학습 흐름 검증

- 변경: 프로젝트별 불변 로봇·과제 원장과 개별/협동 참여 구성을 추가했다. 과제 화면에서 자료·방법·실제 host를 선택하고 지속 경험·평가·모델 receipt까지 같은 계보를 확인한다. 과제 전달은 자료 소유권을 보존하며 자격은 전달하지 않는다. 최신 중앙 로그인·HF 연결을 보존했다.
- 증거: f5cb33bda891 원격 백엔드 2422통과·78건너뜀, Chromium 167통과. fd889ea429 Model·AI 실제 고정 CPU 환경에서 각각 ACT/HIL-SERL 합성 양팔·3카메라 자료 학습·저장·재적재 검사가 통과했다. 같은 SHA의 OAuth·Account·과제 브라우저 30통과. 각 로그의 NEW 0. 출처·한계는 [검증 기록](../../../docs/validation/learning-tasks-2026-10-22/result.md)에 명시했다.
- gate 변화: 없음. 일반 로봇 실행 어댑터, 실제 HF 동의, 공식 이미지 활성화와 실물 actor·개입·보상·초기화 수용은 별도다.
