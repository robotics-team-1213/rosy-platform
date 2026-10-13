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

## 2026-10-14 · 27b3b81da6 · feat: 공동 학습 계정과 HF 가져오기

- 변경: D-755 사용자·프로젝트 권한, 암호화된 복수 HF 연결, PKCE/OIDC 로그인, 고정 commit 자료 가져오기·취소·재시도와 계정 UI를 연결했다. 인증된 검수자 이력을 남기며 기존 승인 wire를 유지한다.
- 증거: 해당 HEAD의 모델 PC 원격 회귀 135 passed, known_failures 0 NEW. Chromium 1440/320px에서 두 계정 연결·선택·고정 SHA/해시 가져오기·로그아웃 철회를 검증했다. OAuth는 서명된 모의 공급자 HTTP 통합시험이다.
- gate 변화: SOURCE와 모의 공급자 통합 검증이다. 실제 OAuth 앱 미등록으로 외부 로그인·운영 활성화는 미검증이다. 가져온 자료는 pending_curation이며 권리·라벨·시간 정렬과 실제 학습 수용을 자동 승인하지 않는다.
