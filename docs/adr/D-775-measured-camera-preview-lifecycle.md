## D-775 실측 카메라 교정의 승인·저장·적용·무효화는 목적별 기존 소유자를 따른다

**Status:** Accepted (2026-10-16, 사용자 설계·구현 승인; SOURCE·DEVICE·FIELD 별도)

### Context

D-636의 측정 도구는 렌즈 K/D와 별도의 undistorted-pixel 바닥 교정을 만든다.
기존 paint-fit 승인과 runtime tracking Calibration은 raw-pixel homography 하나이므로
비선형 실측 교정을 그대로 넣을 수 없다. 사용자는 D-633·D-636의 운영 연결 뒤
D-598 마커 공백 대응을 진행하도록 요청하고 설계·실행 계획의 구현을 승인했다.

### Decision

1. 첫 단위는 **지도 미리보기 전용**이다. 원본 계보·렌즈·바닥 교정을 결속한 versioned
   JSON 묶음을 공유 ROS-free 계약으로 검증한다. K/D·바닥 후보의 원본 revision과
   묶음 digest를 다시 계산한다. digest는 물리 정확도 증명이 아니다.
2. Fleet의 기존 교정 승인 소유자 아래 preview 목적의 단일 선택과 감사 이력을 같은
   DB에 보존한다. named operator, 명시적 오차 한도, 기대 revision으로 승인·철회를
   원자 처리한다. 기존 tracking 기록과 sighting 허용 revision은 바꾸지 않는다.
3. 기존 calibrations 경로는 목적을 명시한 요청만 preview 기록을 다룬다. source-token
   config는 opt-in한 소비자에게 자기 preview 기록만 준다. Vision의 수치 상태 보고도
   source token에 결속한다. Fleet으로 영상·자격·파일 경로를 보내지 않는다.
4. Vision이 현재 촬영 session을 소유한다. receiver boot·재접속·관찰한 촬영 geometry epoch를 구분하고,
   operator가 source/session/revision/촬영 조건을 명시적으로 확인한 signed lease로만
   측정 미리보기를 연다. 일반 viewer는 상태·확인된 결과만 읽는다.
5. source/map/lens/JPEG 크기·회전이 일치해야 한다. 확인 불가능한 초점·zoom·ISP 조건은
   operator 확인으로 남기며 자동 검증이라고 부르지 않는다. config 적용 lease는
   수신 monotonic 시각부터 최대 5초다. 실패한 갱신은 lease를 연장하지 않는다.
6. config 만료·교체·철회·재접속·조건 불일치 때 적용을 멈춘다. remap 뒤에도 동일한
   generation/session/lease인지 확인한다. 마지막 성공 영상이나 legacy 영상으로 몰래
   대체하지 않는다. 저장 성공과 실제 적용 readback을 구분한다.
7. 실제 측량이 없는 합성 묶음은 승인되지 않는다. 실제 자료를 주장하는 operator와
   그 근거를 기록하며 코드 검증만으로 측량 진실성을 보장하지 않는다. 미리보기 승인은
   마커 높이·카메라 자세·위치 sighting·실물 주행의 승인으로 전파되지 않는다.
8. D-598의 현재 자세와 오차 projection 소유자는 현행 D-630·D-752에 따라 World다.
   Fleet의 identity·admission·감속·traffic 소비는 유지한다. 후속 주행은 기존
   D-587·D-593·D-596 현장 조건과 실측 오차 근거 뒤에 진행한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 contracts/overhead/Fleet/site_ui holder만 확장, 새 최상위 구조·서비스 없음 |
| D-429 | 촬영·수치 계산·운영 승인·명령 권한 분리 유지 |
| D-430 | safety-tagged 소비자 변경은 독립 리뷰·trailer 적용; 새 명령 writer 없음 |
| D-457·D-595 | 기존 tracking 승인·고정 교정·호환 요청 유지 |
| D-633·D-636 | 오프라인 계산을 운영 preview 목적의 검증·승인·소비로 연결 |
| D-766 | 기존 tracking 책임은 Fleet static holder로, 설치 교정 view는 Console 하위 단위로 나눈다. Python import·배포·자산 URL과 승인 소유자는 유지하며 단위별 한도를 낮춘다 |

### Consequences

실측 교정의 선택과 실제 적용 상태를 재시작·철회·source 변경에서도 구분할 수 있다.
현재 촬영과 독립 측량이 없으면 현장 정확도와 D-598 주행 수용은 미검증이다.
구현 순서와 완료 기준은 `docs/plans/2026-10-16-measured-camera-lifecycle.md`를 따른다.
