## D-457 마커 우선과 무마커 폴백으로 천장 카메라 위치를 지도에 표시한다

**Status:** Accepted (2026-10-04, 사용자 구현 지시). SOURCE 구현과 호스트 검증은 장치 배포·현장 수용과 별개다. UI/UX 리팩터링은 이번 범위에 없다.

### Context

- 현장 S21 `ceiling_north` 영상은 들어오지만 네 모서리와 로봇 마커를 모두 요구하는 기존 경로는 지도에 위치를 내지 못한다.
- 사용자는 사각형·차선 추론을 사용하고, 마커가 있으면 그것을 우선하며 없으면 무마커로 폴백하도록 지시했다.
- 기존 `feat/overhead-markerless-tracking` 브랜치의 2026-10-01 설계·시험을 현행 경로에 통합한다. 그 브랜치의 D-405 번호는 현행 아이콘 ADR과 충돌하므로 이 결정은 별도 D-457이다.
- 등록된 로봇의 `map_id`가 null인 현장에서는 odom 좌표로 이름을 추론하지 않는다(D-455). 등록·토큰을 보존한다.

### Decision

1. **보정 우선순위.** 현재 프레임에 모서리 마커 네 개가 있으면 측정 homography를 쓴다. 없으면 설치 화면에서 사용자가 승인한 D-375 사각형·차선 맞춤 기록을 쓴다. source/map/lens와 화면 비율을 검사하며 불일치·기록 없음은 `CALIBRATION_REQUIRED`다. 같은 비율 해상도 변경은 배율로 보정한다. 이 기록은 표시 전용이며 CORE 지도·localization을 갱신하지 않는다.
2. **로봇 마커 우선.** 설정된 로봇 마커가 보이면 우선 관측한다. 모서리 마커가 가려져도 승인 추론 보정이 있으면 해당 로봇 마커를 투영할 수 있다. `marker_id`는 관측 번호이며 `robot_id`는 Vision이 보내지 않는다. Fleet이 인증된 source의 명시적 `robot_markers` 대응으로만 이름을 확정한다. 대응은 `robot_ids`의 부분집합이고 중복 번호·대상은 거절한다. 무마커 전용 설정은 빈 대응을 허용한다.
3. **무마커 폴백.** 마커가 없는 대상은 익명 배경 blob 검출을 쓴다. 빈 트랙 30프레임 및 최소 10초 학습 뒤 배경을 고정하며, 지름 0.12–0.26 m만 허용한다. 넓은 장면 변화는 `SCENE_CHANGED`로 재학습한다. 마커 우선 관측은 이 배경 학습이 끝나기를 기다리지 않으며 배경 검출은 계속 처리한다. 동일 프레임에서 마커 주변 blob은 중복 제거한다. 명목 회전 반경 0.08257 m와 상단 높이 0.125 m는 D-397 기하이며 hfov를 알면 시차를 보정한다.
4. **계약·수명.** `OverheadDetectionsPayload`는 source/map/calibration/processor revision, captured_at, seq, status와 최대 16개 `{x,y,footprint_m,score,marker_id?}`를 싣는다. 숫자는 유한값이고 marker_id는 음이 아닌 정수이며 프레임 내 중복은 거절한다. 익명 payload는 marker_id를 생략한다. source 전용 token으로만 제출한다. Fleet은 1초 lease와 map/revision·future·stale·순서 검사를 적용한다. 오래된 마커 위치를 폴백 방해에 쓰지 않는다.
5. **이름 대조.** 마커 대응은 `MARKER`로 표시하며 CORE map pose가 없어도 카메라 위치를 보인다. 익명 검출의 이름 대조는 신선한(2초) 같은 map의 `LOCALIZED`/map-frame pose만 사용하고 0.30 m Hungarian gate를 적용한다. localization 필드가 없는 구형 장치는 map_id를 요구하고 미검증 프레임으로 표시한다. 이름이 불확실한 검출은 `unknown`으로 남긴다. 여러 source에서 같은 로봇은 MARKER가 MATCHED보다 우선한다.
6. **표시·권한.** 현재 지도에 위치·상태와 배경 재학습 버튼, X/Y 좌표 표(m)를 추가한다. 좌표는 소수점 두 자리로 표시하고 마커 관측/무마커 추론/이름 미확정을 구분한다. 표시 해상도는 실측 정확도를 뜻하지 않는다. 다음 조회가 멈춰도 서버 age와 요청 지연을 뺀 최대 1초 표시 수명에서 지운다. fresh sighting 레이어가 켜져 있으면 그 로봇의 추론 중복을 숨긴다. tracking 레이어 자체의 MARKER 관측은 pose가 null이어도 그린다. viewer는 조회만, operator는 보정 승인·철회·재학습을 한다. page scope 취소로 이전 토큰·페이지의 늦은 응답을 버린다.
7. **실행 경계.** Fleet은 SQLite 보정·감사 기록과 표시 대조를 소유하고 Vision은 검출만 한다. 명령·교통·미션·localization 입력과 연결하지 않는다. `rosy-vision vision --track`을 명시적으로 활성화한다. 서명된 사이트 후보·배포 후 실제 영상으로 전환·학습·위치 오차를 확인하기 전 DEVICE/FIELD 완료를 주장하지 않는다.

### 구조 관계

| 결정 | 관계 |
|---|---|
| D-427 | 현행 `operations/fleet`, `operations/vision`, `contracts/foundation` 경로를 사용하고 과거 src 트리를 실행 경로로 복원하지 않는다 |
| D-429 | Vision 검출과 Fleet 원장·이름 대조의 소유를 유지한다 |
| D-430 | 새로운 서비스/앱 패키지를 만들지 않고 기존 모듈의 tracking 하위 기능으로 통합한다 |
| D-257·D-268·D-318 | 표시 전용·자동 정책 분리·Fleet 영상 relay 금지를 유지한다 |
| D-375·D-395·D-397·D-455 | 승인 추론 보정, map pose 신뢰, 명목 기하와 odom/map 구분을 따른다 |

### Validation

- 공유 payload 벡터: 잘못된 숫자·상태·중복 marker_id와 익명 직렬화 검사.
- Vision 합성 프레임: 모서리 우선, 승인 보정 폴백, 렌즈·비율 거절, 마커+학습 병행, 배경 변화 검사.
- Fleet 시험: token/권한, lease, 명시적 마커 대응, map pose 대조와 unknown, 영속 승인·철회 검사.
- 브라우저 순수 계산·서빙 시험: 마커 유무 전환, pose 없는 MARKER 표시, 레이어·scope 연결 검사.
- 실제 사이트: 두 로봇과 카메라 연결은 별도 조회 증거다. 배포와 빈 트랙 학습·실물 오차 검증은 아직 완료되지 않았다.
