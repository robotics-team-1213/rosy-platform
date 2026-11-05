# 표면별 카드

진행 중인 평가다. 화면 배치의 D-926 확인은 두 테마의1366×768·390×844이며320px·1440px·1920px·95rem 경계도 기존 해당 회귀에서 유지한다. 상태 행렬은 아래처럼 실제 계약·시험의 뷰포트를 별도로 선언한다. 전체 문서 캡처의 PNG 높이는 스크롤 길이를 포함하므로 뷰포트 높이로 읽지 않는다. 이전1440 셀을1366 셀로 세지 않는다.

| 상태 행렬 묶음 | 선언한 실제 뷰포트와 적용 상태 |
| --- | --- |
| Robot 역할 | 1366×768·390×844, robot-role-matrix.csv60셀. 정상/빈/지연/끊김/미수신/권한/오류/안전 정지/기존 확인·취소. 바뀐 운용 문구는 새 셀로 교체 |
| Monitoring | 기존320×844·390×844·1366×768·1920×1080, 두 테마. 실제 snapshot 네 상태·최초/빈/오류/인증·범위 거부 |
| Games | 1280×800·390×800·320×568. 실제 overlay 네 상태·첫 기동/오류·정지 요청. 정지 요청은 물리 SAFE_STOP 확인이 아님 |
| Learning 조회·검수 | 기존 상태 시험의1440×844·390×844 및 해당320px/800px 셀을 그대로 식별. 조회/쓰기 정상·대기·빈 목록·오류·거부·확인/취소. 최종 캡처 receipt에 정확한 viewport 기록 |
| Learning 홈 | 기존 실제 전환 캡처1366×900·390×900과 새 D-926 배치 셀을 구분. 하위 화면/입력 보존·권한 실패 후 상세 제거 |
| Fleet·Account·Pilot | 각 기존 상태 시험의 선언 크기를 receipt에 연결. 폼/목록 정상·대기·오류/권한·빈 목록과 실제 존재하는 확인/취소. 로봇 원천을 표시하는 값에만 temporal evidence 적용 |
| 진단·차선·갤러리 | 1440·390·320px의 선언된 정적 unavailable/NO DATA만. PARKED·비기능 관찰·DEV를 일반 GO로 올리지 않음 |

Account/login/profile는 rosy_account/web_assets.py의 계정 표면이며 CORE 센서/안전 값을 받지 않는다. 작업 공간은 workspaces.js의 선택 목록이다. 이들의 telemetry 네 상태·SAFE_STOP은 N/A이며 실제 인증/조회/저장 실패와 대기는 평가한다. camera/evaluate/VLM/tasks/SIM 폼도 현재 API의 요청 상태를 쓰며 센서 evidence TTL 계약을 새로 만들지 않는다. 늦은 HTTP 응답과 오래된 센서 판정은 다르다. 불가역 확인은 현재 존재하는 동작에만 적용한다.

공통 완료 조건은 현재 G1, 적용 상태 전체 G2, G3 여덟 항 및 D-926, 최종 소스의 main ancestry다. 아래의 ‘관찰 범위 위반 없음’은 전체 GO가 아니다. 원본 경로는 작업 공간 `docs/workspace-records/2026-11-05/ui-map/`, 파일 지문은 [captures.sha256](captures.sha256)를 따른다. 단계 완료는 서버 원천이 있을 때만 표시하며 선택·현재 위치를 승인으로 바꾸지 않는다.

## Fleet·Account

| 카드 / 표면 질문 | 소스·대표 셀 | 현재 판정 / 남은 조건 |
| --- | --- | --- |
| 관제 — 어느 로봇·작업에 개입하는가 | c5142a2e20 + 4f76500d98 + 1ea8e59bf5; fleet-folds/console-preferences-dark-390.png | 열린 설정 G3 승인. 전체 상태 셀·후속 착지 대기. 작업 단계 owner 미제공은 임의 노선으로 채우지 않음 |
| 설치·보정 — 준비된 것과 다음 행동은 무엇인가 | c5142a2e20; fleet-sample-final/fleet-install-dark-390.png | 관찰 범위 위반 없음. 전 상태 셀 결속 필요, 운영 설치 수용 별도 |
| 팔레트 적재 준비 — 저장·미리보기·제안 중 어디인가 | 4c8a3858e0; g2-supplement-final/r6-cell-fullpage | ADR 식별자 수정·안전 안내 보존, 새 셀 G3 승인. 최종 G1/착지 대기. 실제 실행 단계는 owner 계약 별도 |
| 현장 지도 — 어떤 지도를 편집·검증하는가 | 6abcb21272; inspector/site-map-inspector-light-320x568.png | 관찰 범위 위반 없음. 공식 착지와 전 상태 결속 대기 |
| 정책 승인 — 어떤 제안을 누가 승인하는가 | c5142a2e20; fleet-sample-final/fleet-policy-dark-390.png | 샘플 승인 창 없음은 빈 상태 근거. 실제 확인 셀과 전 상태 결속 필요. 승인·배포 수용 별도 |
| 계정 관리 — 누구에게 어떤 권한을 주는가 | c5142a2e20; robot-fleet-final/accounts-dark-320.png | 긴 값·편집 폼 관찰 범위 위반 없음. 상태·확인 셀 결속 필요 |
| 내 계정 — 내 정보와 비밀번호를 어떻게 바꾸는가 | 4c8a3858e0; g2-supplement-final/r6-browser·r6-sample | 주 동작 하나·공용 행·평문 권한/원본 진단 수정, 새 두 테마 셀 G3 승인. 최종 G1/착지 대기 |
| 로그인 — 어떻게 인증하고 실패에서 복구하는가 | c5142a2e20; robot-fleet-final/login-managed-320.png | 한 주 동작과 관리자 안내 관찰. 인증 전 앱 상태를 추가하지 않음. 오류·거부 셀 결속 필요 |
| Learning 입구 — 어느 학습 호스트로 가는가 | 6abcb21272; robot-fleet-final/learning-dark-390.png | 미등록 안내 관찰. fleet-sample-final의 JSON NOT_FOUND 그림은 증거에서 제외. 실제 운영 앱 등록 별도 |

## Learning 이전 관측 — 최종 상태는 아래 별도 표를 따른다

| 카드 / 표면 질문 | 대표 셀·구현 | 현재 판정 / 남은 조건 |
| --- | --- | --- |
| 홈 — 무엇을 시작하거나 이어 하는가 | home-subviews/learning-home-routes-dark-1366.png; b967a8e08e | 실제 하위 화면·권한 실패 정리 task review 통과. 경로 줄 R5, 상태·확인 셀 및 착지 대기 |
| 로봇·과제 학습 — 저장 과제와 다음 작업은 무엇인가 | learning-comparison-final/learning-map-learning-tasks-light-1366.png | 빈 목록 관찰. 경로 줄 R5, 생성/선택/실행 상태 셀 필요. 실제 학습 품질 별도 |
| 로봇암 시범 검수 — 어떤 단계·자료를 확인하는가 | shared-stations/omx-common-stations-dark-1440.png; 2593961d98 | HOLD: 프로필 중첩 접힘·파일 선택기·경로 줄 R5. 실제 시연 준비를 추정하지 않음 |
| 객체 검수 — 어떤 사진·박스를 확인·승인하는가 | shared-stations/review-hierarchy-objects-light-1440x900.png | HOLD: 다수 접힘·경로 줄 R5. 사진 우선·명시 승인·사람 라벨 보존 |
| 픽셀 검수 — 어떤 영역을 수정·승인하는가 | shared-stations/review-hierarchy-pixels-dark-390x844.png | HOLD: 다수 접힘·접힌 자료 준비·경로 줄 R5. 원본/마스크·초안·사람 수정·승인을 구분 |
| VLM 판단 — 확정 정답과 모델 의견을 어떻게 비교하는가 | shared-stations/vlm-collaborator-stations-light-390.png | 공용 표·현재 위치 및 관리자 역 숨김 검증. HOLD: ADR·파일 선택기·경로 줄 R5. 모델 품질 별도 |
| 평가·승격 — 어떤 근거가 있고 누가 승인하는가 | learning-comparison-final/evaluation-context-light-1366.png | 근거와 요청 분리 관찰. HOLD: ADR·요청 해시·경로 줄 R5. 측정은 승격 승인이 아님 |
| 자료 등록 — 자료를 어떻게 등록해 검수로 이어 가는가 | learning-comparison-final/learning-map-catalog-dark-1366.png | HOLD: 기본 영어 파일 입력·경로 줄 R5. 기존 승인/출처와 실제 입력 계약 유지 |
| 카메라 맞춤 — 어떤 촬영 기준과 비교하는가 | learning-comparison-final/learning-map-learning-camera-light-320.png | 기준 미설정 시 판정 차단. HOLD: 파일 선택기·경로 줄 R5. 비교 영상·보정 수용 별도 |
| SIM 실험 — 조건과 실행 연결이 준비됐는가 | learning-comparison-final/learning-map-learning-sim-light-1366.png | 연결 미설정을 정직하게 표시. 경로 줄 R5, 실행·오류 셀 결속 필요. SIM 과제 성공 별도 |
| 계정과 외부 자료 — 누가 어떤 연결·동의를 준비하는가 | learning-comparison-final/learning-map-accounts-light-320.png | 익명 진입은 D961 인증 틀/경로 줄 예외. 로그인 후 일반 프레임의 경로 복원은 R8에서 검증 중. 연결/동의·만료 상태 셀 결속 필요 |
| 작업 공간 — 현재 센터와 다른 공간의 범위는 무엇인가 | learning-6082/learning-map-learning-workspaces-light-320.png | 현재 센터·미등록을 구분. 원래 캔버스에 없던 화면은 실제 선택 역할 기준. 경로 줄 R5·등록 목록 상태 셀 결속 필요 |

## Robot·관측·기타

| 카드 / 표면 질문 | 대표 셀·소스 | 현재 판정 / 남은 조건 |
| --- | --- | --- |
| Robot 콘솔 — 운전 가능한가, 무엇이 막는가 | 4c8a3858e0; g2-supplement-final/r6-browser/operator-console-mode-feedback-390x844.png | 기본 평문·현재 producer 어휘 보완, 새 셀 G3 승인. 기존 정지 계약/근거 보존, 최종 G1/착지 대기 |
| Robot 설치 — 어떤 준비 작업이 필요한가 | robot-fleet-final/administrator-setup-safe_stop-1366x768.png | 안전 정지→독립 작업→근거 순서 관찰. 가짜 준비 단계 없음. 전 상태 셀 결속 필요 |
| Robot 장치 — 호스트 상태와 가능한 관리 작업은 무엇인가 | 22935ec44f; host-tables-final·robot-role-matrix.csv | 전체 role/긴 값171개 통과, 새 표 캡처 G3 여덟 항 승인. 최종 소스 통합·G1·착지 대기 |
| Games — 점수와 관측은 현재 것인가 | 6abefcfdad; games-matrix-final | 기존7상태×3폭21 PNG/3 passed/NEW0 회수, G3 근거 결속. 최종 G1/ancestry 대기, 실제 경기·물리 정지 수용 별도 |
| 진단 — 센서·제어 연결 근거는 무엇인가 | static-final/diagnostic-unavailable-390.png | PARKED(D-266). 연결 불가 정적 렌더만 검증, 조작/서비스 재활성화 주장 없음 |
| 차선 라이브 — SIM 영상·인식 근거가 있는가 | static-final/lane-live-unavailable-320.png | 연결 불가·NO DATA 정적 셀만 관찰. 라이브 SIM 성공은 별도, 일반 업무 GO로 세지 않음 |
| Monitoring — 어느 원천·보고가 지연·누락인가 | dark-surfaces/fresh-390x844-dark.png | 원천·판정·나이 구분. 기존 상태 회귀와 전 셀 결속 필요. 운영 서비스 수용 별도 |
| Pilot — 어느 로봇에 어떻게 접속하는가 | dark-surfaces/pilot_long_names_320x568.png | 긴 이름·확인 중·로봇 선택 관찰. 오류/권한 상태 결속 필요. 실물 조종 수용 별도 |
| 부품 갤러리 — 어떤 공용 부품을 쓰는가 | static-final/gallery-unavailable-1440.png | DEV. 제품 업무 완료·실물 상태로 세지 않음. 실제 소비처는 DESIGN.md 목록 |

## Learning 최종 상태 — 12개 카드

앞 Learning 표의 HOLD는 수정 전 이력이다. 현재 제품42c97133c1은733441ec49/6478fe9b27까지 동일하며 아래 판정으로 대체한다. 전체 관련440개·홈25개, G1241개, 강화한 권한 query36개는 각각0 skip/NEW0이다. 독립 G3 여덟 항은 README의 최종 표에 결속한다. 최종 전 브랜치 리뷰·공식 착지는 대기한다.

| 카드 | 최종 원본(learning-depth-final-42c97133c1/ 아래) | 현재 판정 |
| --- | --- | --- |
| 홈 | learning-home-routes-dark-390.png | 실제 하위 화면·입력 보존·공통 갱신·권한 실패 정리. G3 PASS |
| 과제 | learning-map-learning-tasks-light-1366.png | 빈 목록·생성·선택·전문가 새 경로 실제 이동. G3 PASS, 학습 품질 별도 |
| OMX | learning-map-learning-omx-dark-390.png | 주 프로필 section·기존 hash 이동·현재 역·한국어 선택. G3 PASS, 시연 준비 추정 없음 |
| 객체 | review-hierarchy-objects-light-390x844.png | 사진·명시 승인·별도 준비·키보드·403 후 차단. G3 PASS |
| 픽셀 | review-hierarchy-pixels-dark-390x844.png | 보존DOM 도구·별도 준비·AI 작업 진단 한 겹·사람 라벨/초점 보존. G3 PASS |
| VLM | learning-map-learning-vlm-light-390.png | 사람 정답/모델 의견·역·관리자 숨김·한국어 선택. G3 PASS, 모델 품질 별도 |
| 평가·승격 | learning-map-learning-evaluate-dark-1366.png | 근거/요청·현재 hash 초기화·403/지문 변경 차단·Fleet 권한. G3 PASS |
| 등록 | learning-map-catalog-light-390.png | 한국어 선택·실제 파일명/초기화·기존 입력 계약. G3 PASS |
| 카메라 | learning-map-learning-camera-light-320.png | 기준 미설정/지문 변경 차단·선택·경로. G3 PASS, 실제 보정 별도 |
| SIM | learning-map-learning-sim-dark-390.png | 조건·미연결·오류·경로. G3 PASS, 과제 성공 별도 |
| 계정 | 별도 account-context-final/1f3ffb26e7/account-context-signed-in-light-390.png | 익명 D961 예외·로그인 후 경로·만료/로그아웃 복원. R8/최종 G3 PASS, 운영 SSO 별도 |
| 작업 공간 | learning-map-learning-workspaces-dark-390.png | 현재 센터·미등록·조회 오류·선택 목록·경로. G3 PASS |

현장 지도6abcb21272는 공식 main3a004fad06에 착지했고 source ancestry를 확인했다. R3 장치 표·R6 문구·R4 지도 설정의 현재 G1은 위 공통241개에 포함되며 각 독립 G3 승인과 관련 회귀는 README에 결속한다. 나머지 표의 전체 상태 결속 대기는 기존 실행·원본 셀을 아래 source 상태 목록과 함께 대조해야 하며 PNG 존재만으로 일반 GO를 선언하지 않는다.

전체 G3는 정직·증거 상태·색·위계·불가역·어휘·질문·문법을 [README](README.md)에 결속한다. 서로 다른 SHA 그림은 수정 전/후 이력을 유지한다. 새 코드와 다른 그림을 최신 증거로 간주하지 않는다.
