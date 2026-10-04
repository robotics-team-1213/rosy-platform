## D-462 Pinky 반복 검수는 프레임 정체성·객체/픽셀 독립 revision·최신 결정 확인을 보존한다

**Status:** Accepted (2026-10-05, 사용자 다중 영상·픽셀 검수·CAD 연결·직접 세션 협업 지시)

### Context

기존 웹앱은 네 객체 사진을 영속 검수한다. 새 영상 JPEG/edge PNG 355개 표현은 같은
영상 SHA/프레임 2쌍을 포함한다. 353개 원본 프레임 정체성을 구별하고 현재 네 결정은
보존해야 한다. CAD 파일 출처는 확인됐으나 촬영 지도 revision/pose/calibration은 없다.
기존 crosswalk/stop_line train/val 픽셀은 0이며 CAD 투영은 사람 정답이 아니다.

### Decision

기존 앱/SQLite를 확장한다. 소유자는 기존 GUI 세션이며 학습 루트와 분리된 app 경로만
고친다. 검증 입력 폴더를 앱에서 등록하고 원본 이미지 SHA/크기와 선언된 영상 SHA/frame,
source_session/capture_group을 저장한다. 같은 영상 SHA/frame의 JPEG/PNG는 한 프레임의
표현으로 묶는다. 원본 MP4의 직접 검증 여부는 별도 사실이다. 새 객체·마스크는 pending이다.

마스크는 기존 이름 background/lane_line/wall/drivable/stop_line/crosswalk의 labelmap에
묶인 원본 크기 index PNG다. 초안 ZIP 색을 엄격히 검증해 index로 옮기며 마스크가 없으면
ignore_index=255로 시작한다. 브러시/전체 class 채움/되돌리기·영속 저장과 독립 version
CAS를 제공한다. 사진 전체와 기본 배경의 명시 확인 없이는 승인하지 않으며 편집하면
pending으로 돌아간다. 객체 제외는 모든 학습 export에서 해당 프레임을 제외한다.

CAD 참조 등록은 모든 파일 SHA/크기와 graph source SHA를 검증한다. 영상·지도 연결은
검증된 영상/frame/image 참조와 공칭 지도 출처의 나란한 표시다. 실제 camera projection은
recording revision·동기화 pose·intrinsics/extrinsics 증거가 없으면 unverified로 남는다.
CAD로 마스크를 자동 생성하거나 승인하는 경로는 만들지 않는다.

기존 객체 receiver COMPLETE/manifest를 유지하고 별도 `review-contract.json` 및
`AUTHORITY_COMPLETE`로 모든 객체/마스크 revision·승인/대기/제외와 파일 SHA를 동결한다.
workspace_id/generation/decision digest를 명시한다. 소비자는 `/api/decisions`의 현재 결정과
snapshot을 대조하고 최신 제외/수정이 있으면 오래된 export를 거부한다. 자기 완결적 과거
export만으로 최신 결정 권위를 추정하지 않는다. 학습 루트가 독립 receiver/build 검증을 소유한다.

| 구조 계약 | 관계 |
|---|---|
| D-427 | learning developer 도구만 확장, 새 최상위 part 없음 |
| D-429 | 기존 app source/server·공용 자산 소유 유지 |
| D-430 | 로봇 writer·HOLD·정책 권한·모델 활성화 변경 없음 |

### Verification and consequences

실제 입력 해시/중복·legacy row 보존·pending·mask color/bounds/CAS·current export 계약을
호스트와 Chromium에서 확인한다. 운영 state의 새 자료 등록은 pending만 추가한다.
실제 승인 시험은 별도 state에서 수행한다. 물리 장치·학습 수용·CAD 투영 증거는 별도다.
