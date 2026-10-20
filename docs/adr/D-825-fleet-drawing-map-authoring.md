## D-825 STL 도면 참조와 Fleet 평면 지도 편집

**Status:** Accepted (2026-10-21)

### Context

운영자는 설계 자료 위에서 도로·목적지·구역을 직접 편집하고 템플릿으로 복사해야 한다. 기존 D-488/D-635의 초안·프로필·활성화와 D-655의 조사 기준·검토·busy/CAS 경계를 재사용한다. 기존 STL 변환기는 특정 코스의 단위·축·도형을 가정하므로 범용 등록 경로가 될 수 없다.

### Decision

1. 첫 입력은 ASCII/binary STL이다. 원본 해시, 변환기 버전, 명시적인 평면·단위·축척·원점·방향을 보존한다. 투영 결과는 참조 배경이며 자동으로 운행 도로·현재 로봇 위치가 되지 않는다. 다른 CAD 형식은 실제 파일과 정확도 검증 후 추가한다.
2. `DrawingTransform`과 `DrawingReference`의 정본은 ROS-free `core_common.protocol.site_drawing`이다. `rosy.site_map/1`의 선택 `drawing`은 원본·projection 해시만 저장하고 `survey.revision`을 projection 해시에 묶는다. 선택 도로 `name`은 ID와 다르며 기존 참조를 바꾸지 않는다. 없는 선택 필드는 기존 body/hash에서 생략한다.
3. Fleet는 인증된 raw STL 업로드·제한된 자식 변환·내용 해시 보관을 소유한다. 원본과 projection은 기존 지도 JSON 밖, 해당 tasks DB의 영속 데이터 디렉터리에 보관한다. 임의 파일 경로·외부 URL을 받지 않는다. 상세 DTO·경로·오류·자원 제한은 API v1.291이다. 기존 인증·named operator·CSRF와 감사 경계를 유지한다.
4. Console은 기존 survey 편집을 선택·그리기·꼭짓점 수정·삭제·undo/redo·숫자 입력으로 연결한다. 저장은 초안/템플릿만 변경한다. 도면 교체는 기존 편집 geometry를 이동·삭제하지 않고 검토 완료를 해제한다. 템플릿 복사는 새 map_id와 미검토 상태를 사용하며 현장 교정·teach·로봇 앵커 증거를 계승하지 않는다.
5. 활성화는 명시적 검토·CAS와 기존 trip/formation/teach busy 차단을 유지한다. 위치/교정의 유효성은 별도 현장 증거다. 편집은 로봇 명령을 보내지 않으며 실행은 기존 Fleet admission과 CORE 최종 이동·정지 권한을 따른다.
6. 기존 source-holder 등록으로 지도/teach backend와 지도 UI를 응집된 단위로 분리한다. 기존 Python import와 공개 웹 URL은 유지한다. 파일/단위 크기 기준·기존 실패·안전 조건을 완화하지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 operations/Fleet·Console·contracts 소유권 안에서 배치한다. 새 최상위 part나 호스트를 만들지 않는다. |
| D-429 | 도면은 참고 자료다. World의 현재 위치·관측, Fleet의 원장/admission, CORE 장치 실행의 소유권을 바꾸지 않는다. |
| D-430 | source 이동에서도 안전 anchor·import·설치 경로와 독립 검토를 보존한다. 별도 Base writer를 만들지 않는다. |

### Consequences

신규 지도 등록은 원본/참조 자료와 운영 지도 revision을 분리한다. 기존 지도는 해시와 API 호환성을 유지한다. 파일·복잡도·시간·용량 제한을 초과하면 일부 geometry를 몰래 버리지 않고 명시적으로 거절한다. 승인된 설계와 구현 순서는 2026-10-20 설계안과 2026-10-21 구현 계획이다.

Accepted는 설계 결정이다. 구현·실제 파일 변환 정확도·현장 교정·실물 좌표 이동·군집 주행을 완료했다는 뜻이 아니다.
