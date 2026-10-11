## D-631 지도 프로필과 표시 모드

**Status:** Accepted (2026-10-11, 사용자 요청; 배포·현장 수용 별도)

### Context

사용자는 같은 좌표를 2D 선 지도, 교정 영상 오버레이, 원본 영상으로 보고, 교정 전후를 비교하며 여러 지도를 저장·불러오기를 요청했다.

### Decision

1. 관제 표시 모드는 `coordinates`, `overlay`, `camera`. 기본은 2D 좌표. 교정 후 영상은 신선한 프레임과 승인된 동일 지도·렌즈·크기 교정이 있을 때만 표시한다. 원본은 회전·교정하지 않는다. 지도 선택과 표시 모드는 로봇 명령을 보내지 않는다.
2. `SiteMapStore`에 이름 있는 프로필을 별도 저장한다. 활성 버전과 초안은 그대로 유지한다. 프로필 보기·저장은 활성 지도를 바꾸지 않는다. 초안에 불러온 후 기존 명시적 활성화와 진행 중 경로 거절을 따른다.
3. API: `GET /api/fleet/site-map/profiles` → `{profiles: [{profile_id,name,revision,saved_by,saved_at,map}]}`; `PUT /api/fleet/site-map/profiles/{profile_id}` 요청 `{name,map,expected_revision}` → 저장된 행. ID는 영문·숫자·점·밑줄·하이픈 1–64자, 이름 1–64자. GET은 기존 read guard, PUT은 이름 있는 운영자. 요청 2 MiB 제한, 기존 `rosy.site_map/1` 좌표·참조 검증, revision 비교 실패는 409 `SITE_MAP_PROFILE_CHANGED`. 이벤트 `profile_saved` 기록. 최대 100개, 새 프로필 초과는 409 `SITE_MAP_PROFILE_LIMIT`.
4. 파일·규칙 입력은 canonical `rosy.site_map/1` JSON. 장소 좌표(공유 map, m), 차로 polyline·방향·폭·속도 규칙을 기존 검증기로 검사한다. 입력 오류는 기존 `SITE_MAP_INVALID` 422. 임의 파일 경로·실행 코드·외부 URL을 받지 않는다. 프로필 미리보기에는 로봇과 운행 경로를 겹치지 않는다.

### Consequences

처음 보는 지도도 좌표 규칙 JSON 또는 파일로 저장해 2D로 볼 수 있다. 사진 교정은 설치·보정에서 해당 지도에 승인해야 한다. STL·이미지에서 차로를 자동 추론하는 기능은 이 계약에 포함하지 않는다. 원격 계약·브라우저 시험과 실물 운행 수용은 별도 증거다.
