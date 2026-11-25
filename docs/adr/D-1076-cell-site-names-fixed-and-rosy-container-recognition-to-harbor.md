## D-1076 셀 자리 이름은 `rosy.cell-site-map.v1` 하나로 고정하고, 컨테이너 인식은 Rosy가 `top` 카메라로 처리해 자리별 결과로 Harbor에 넘긴다

**Status:** Proposed (2026-11-23, 사용자 결정 「rosy가 처리해서 넘기는 걸로」 · 「자리 이름도 다 정해졌잖아 저걸로 픽스」). 승인: 관제·Fleet 장원종, 비전 윤영민, OMX 김승용·서정민, Harbor 담당. 구현·실물 수용은 별도다.

**관련:** D-797 §5(Proposed, `camera_item_pose`), D-1063(Proposed, 공급암 S `top` 카메라 판정), D-1062(Accepted, 천장 트랙), D-1065(Proposed, 카메라 역할 이름), D-1073(`cell-site-map`을 37자리 정본으로 씀), D-328 §1·§4(운영자 확인은 성공 증거가 아님), D-18(API 확정 순서). Harbor 쪽: HarborLogi ADR 0032(자리별 ROSY 인식, 제안), ADR 0036(자리별 비교를 0032 뒤로 미룸).

### Context

- 자리 이름은 이미 `shared/web/cell-site-map.json`(`schema: rosy.cell-site-map.v1`, `revision: 1`, `status: planned_unverified`) 한 파일에 있다. 37자리다: `yard` 3행×2슬롯×3단, `temp_a`·`temp_b` 3행×1슬롯×3단, `stand` 1자리(`stand:r1-s1-t1`). 정식 ID는 `<zone>:r<행>-s<슬롯>-t<단>`이다. 자리가 아닌 곳(`belt`, `supply_s`, `ship_stern`, `ship_bow`, `vehicle_tray`)은 `not_places`에 있다. 옛 이름은 `aliases`(`legacy_layout`·`legacy_sim`·`legacy_station_zones`)로 대응한다.
- 바깥으로 나가는 이름(wire ref)은 `operations/fleet/fleet/pipeline/cell_site_targets.py`가 `<area>-r<row>-c<슬롯 첫 열>-l<tier>`로 만든다(예: `yard-r1-c4-l1`). Harbor는 이 정본을 「검증 안 됨」으로 들여오고(`harbor/cell_site_map.py`, HarborLogi PR #103), 화면 안에서는 야드를 18칸(`Y11`~`Y36`)으로 그린다. 슬롯 가운데 열(`c2`, `c3`, `c5`, `c6`)을 쓰는 이름은 정본 37자리에 없다.
- Harbor는 지금 셀 탑뷰를 **원본 JPEG**로만 받는다: `GET /api/fleet/vision/sources` → `POST /api/fleet/vision/lease` → `GET /api/vision/sources/{id}/frame`(`harbor/rosy_vision.py`). 사진은 화면 표시에만 쓰고, 야드 점유는 사람이 손으로 등록한다(`grid-placement-v1`).
- 11월 23일 작성 당시 Rosy main에는 자리별 컨테이너 점유·신원을 내는 계약이 없었다. `schemas.py`에 상자 모델이 없고, D-797 §5 `camera_item_pose`와 §4 `cell-source-observations`는 Proposed이며 코드가 없다. 셀 안 인식(`deploy/robot/omx/cell_objects.py`, `cell_object_pose.py`)은 셀 스크립트 안에서만 쓰고 Fleet으로 보내지 않는다. 처리된 overhead 결과는 천장 카메라의 Pinky 트랙(`POST /api/fleet/detections` → `GET /api/fleet/tracking`, `display-only`) 하나다.
- 11월 26일 확인 기준, Fleet Wave 4 통합은 자리별 관측을 수신하는 POST와 최신 관측을 읽는 GET을 구현했다. 기동 후 발행 전에는 GET이 404를 반환한다. 최신 스냅샷은 프로세스 메모리에 보관한다. 근거는 [Fleet 라우트](https://github.com/robotics-team-1213/rosy-platform/blob/34a8530e1fd6921b89fa2a31003a6675eeb2d3b4/operations/fleet/fleet/server/recognition/cell_site_recognition_routes.py)와 [통합 시험](https://github.com/robotics-team-1213/rosy-platform/blob/34a8530e1fd6921b89fa2a31003a6675eeb2d3b4/operations/fleet/test/test_wave4_integration.py)에 있다.
- Harbor가 원본 사진에서 컨테이너를 직접 인식하면, 카메라 보정·자리 좌표·카메라 역할을 Harbor에 다시 만들어야 하고 Rosy와 둘이 어긋난다. 팀 원칙도 「비전은 발행, 판단은 관제」다.

### Decision

1. **자리 이름은 `rosy.cell-site-map.v1` 하나로 고정한다.**
   - 정식 ID는 `<zone>:r<행>-s<슬롯>-t<단>` 37개다. 새 자리·이름 변경은 이 파일의 `revision`을 올려서만 한다. 다른 저장소·모듈이 따로 이름 표를 두지 않는다.
   - 바깥 계약(Harbor 포함)에서 자리를 가리킬 때는 wire ref `<area>-r<row>-c<슬롯 첫 열>-l<tier>`만 쓴다. 슬롯 가운데 열을 쓰는 이름은 받지 않는다(거절 사유를 돌려준다).
   - Harbor 화면의 18칸은 표시용이다. `Y{행}{1..3}`은 `yard-r{행}-c1`, `Y{행}{4..6}`은 `yard-r{행}-c4` 슬롯으로 접어서 계약에 쓴다.
   - 이름은 고정하지만 좌표는 아니다. 자리별 좌표·`physical` 값은 `status: planned_unverified`로 두고, 실측 수용(D-933 마커 보정)은 별도다.
2. **컨테이너 인식은 Rosy가 처리한다.** 생산자는 Rosy 비전(셀 `top` 카메라, D-1065 역할 이름)이다. 카메라 보정 revision과 `cell-site-map` revision을 고정해 자리별 결과를 만든다. 결과 한 줄은 자리 하나다:

   | 필드 | 뜻 |
   |---|---|
   | `site_ref` | wire ref (`yard-r1-c4-l2`) |
   | `state` | `EMPTY` \| `OCCUPIED` \| `UNREADABLE` |
   | `object_class` | 컨테이너 종류(색·크기 클래스), 모르면 null |
   | `object_ref_read` | 읽은 화물 코드(마커·라벨), 못 읽으면 null |
   | `confidence` | 0~1 |

   관측 시각(`observed_at`, UTC), 스냅샷 식별자(`snapshot_id`), 출처(`source_id`)와 보정·자리표 판 번호(`calibration_revision`, `site_map_revision`)는 스냅샷에 둔다.

   - 한 번의 관측은 그 카메라가 보는 모든 자리의 줄을 함께 낸다(스냅샷). 가려지거나 확신이 낮은 자리는 `UNREADABLE`이고, 추측해서 `EMPTY`로 쓰지 않는다.
   - 이 결과는 관측이다. 팔 단계 성공 증거(D-797 §5 `camera_item_pose`)나 공급암 S 인계 판정(D-1063)을 대신하지 않는다. 같은 카메라·보정을 쓰므로 생산자 코드는 공유할 수 있다.
3. **Fleet이 읽기 API로 내보낸다.** 현재 경로는 `GET /api/fleet/cell-site-recognition`이다. 관측 생산자는 인증된 POST로 관측을 발행한다. Harbor 서비스 주체(`harbor`)는 읽기 계약을 사용한다. 스냅샷 장기 보관 개수와 유효 시간은 D-18 절차에서 확정한다.
4. **Harbor는 결과만 쓴다.** Harbor는 받은 스냅샷을 야드 화면과 보관 장부 비교에 쓴다. 장부와 다르면 Harbor가 사람 확인으로 보류한다(HarborLogi ADR 0032·0036). 원본 탑뷰 사진은 화면 참고용으로만 남고 점유·신원 판정에 쓰지 않는다. Harbor는 Fleet에 쓰지 않고, 이 결과로 팔·Pinky에 명령하지 않는다.
5. **Pinky 위치는 지금 있는 것을 쓴다.** 새 계약을 만들지 않는다. Harbor가 Pinky 위치가 필요하면 `GET /api/fleet/tracking`(천장 카메라 기준, `display-only`)을 읽는다.

### Consequences

- Harbor의 「자리별 ROSY 인식」(ADR 0032) 요청에 Rosy 쪽 답이 생긴다. 필드 이름은 이 ADR 표를 기준으로 Harbor가 맞춘다(`slot_ref` → `site_ref`, `read_state` → `state`).
- Harbor 시험에 남은 가운데 열 이름(`yard-r1-c2-l1` 등)은 계약 쪽에서 거절된다. Harbor가 고친다.
- 비전 쪽 새 일: `top` 프레임 → 자리별 판정(가림·조명 포함), 보정 revision 기록. 실물 정확도 수용 기준은 구현 PR에서 정한다.
- Fleet 쪽 남은 일: 운영 보관 정책, 유효 시간, Harbor 서비스 주체 권한과 현장 소비자 검증, API Reference 항목.
- 실배포 프로필에서 켤지는 구현 뒤 실물 수용 때 정한다. 그 전까지 Harbor는 지금처럼 사람 등록 관측을 쓴다.

### 남은 것

- 구현한 GET·POST를 API Reference와 소비자 시험에 연결한다. 보관 개수와 유효 시간은 미결이다(D-18).
- 현장 수용은 제안과 별도로 검증한다. 실물 상단 ROI 이름 결속은 A·B 지정 선박 칸 2개에서 확인했다. 나머지 네 영상 칸의 이름 ROI, 지정 팔 좌표, 선박과 임시대의 받침 깊이 기준이 미등록이다. 관측으로 이송을 승인하지 않는다.
- `object_ref_read`를 무엇으로 읽을지(마커·라벨·색). 실물 컨테이너에 개별 식별 표시를 붙일지는 정하지 않았다(정하기 전에는 `object_class`까지만 낸다).
- `top` 카메라 하나로 가려지는 자리(3단 아래)를 어떻게 보는지. 가려진 자리는 `UNREADABLE`로 두고 Harbor 장부를 믿을지 여부.
