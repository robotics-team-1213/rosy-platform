# Pilot에서 운용 지도로 이동 (2026-10-08)

## 범위와 판정

Pilot `/pilot`의 운전자 화면과 Robot Console `/console`의 책임을 나눴다. Pilot은 카메라와 수동 조종을 맡고, 운용 지도·경로·위치·SLAM 표시는 Console로 연결한다. 화면 상단의 `운용 지도`는 목표 내비게이션 기능이 없는 로봇에서도 접근할 수 있다. 조종부에서 지도 목표를 운전 모드처럼 보이게 하던 버튼은 제거했다. 지도에서 목표를 실행하는 기능을 이번 변경으로 추가하지 않았다.

로컬 브라우저에서 전후 화면과 이동 순서를 확인했다. D-153 전체 G2/G3, 설치본, DEVICE, FIELD 판정은 **HOLD**다.

## 전후 화면

| 화면 | 변경 전 | 변경 후 |
|---|---|---|
| 390×844 Pilot 주행 | 상단 `Rosy Robot`은 `/dashboard`, 조종부 `지도 목표`는 capability에 따라 비활성 | 상단 `운용 지도`는 `/console`, 조종부의 가짜 모드 제거. 비상 정지 노출 유지 |
| 2000×1200 Pilot 주행 | 지도 진입과 수동·자동 모드가 서로 다른 위치에 혼재 | 상단에서 지도 진입, 운전 모드는 실제 Pilot 조작만 표시 |

전후 PNG 원본은 `X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-map-handoff-8c3e/evidence/{before,after}/pilot-map-handoff-{390x844,2000x1200}.png`에 있다. 모두 개발 시험 서버의 합성 CORE 응답을 사용한 LOCAL 캡처다. 이 시험의 `/console` 응답은 이동 순서 검사만을 위한 HTML 대역이므로, 이동 뒤 실제 Console의 지도 화면을 찍었다는 뜻이 아니다.

| 캡처 | SHA-256 |
|---|---|
| before 390×844 | `2FDD311D6EB1D1B3B969ECBF9237B655E359CD4E0A8C35A06DD4B95911D99CAA` |
| after 390×844 | `78106A64E636CF1884ED6DC698E79881951DB816DCED6BD7754B17857FD3A9AD` |
| before 2000×1200 | `A079C7BCF1D8B79F333DFE82E4A20747DBAEE5B9D1A618D395D2409ABE4C363C` |
| after 2000×1200 | `D8DACB0FF1A96EE65CAEC6EEBBED14101BB17A1F42A0074F4EB25153EE3564C9` |

## 조종 인계와 검증

주행 중 상단 버튼을 누르면 Pilot은 0 속도 전송을 요청하고, 이 화면이 실제로 잡은 MANUAL 모드만 IDLE로 돌리는 요청을 마친 뒤 Console로 이동한다. 요청이 끝없이 대기하지 않도록 모드 요청에는 3초 제한을 둔다. 중복 클릭과 모드 진입 요청 도중의 이탈도 처리한다. 보정 소유자가 다른 경우에는 기존 규칙대로 이 화면에서 IDLE을 보내지 않는다. 브라우저 화면 이탈 시 요청 성공은 실제 로봇 정지나 물리적 readback의 증거가 아니다.

- 새 브라우저 시험: 390×844와 2000×1200에서 `/console` 요청 전에 개발 서버가 0 속도와 IDLE을 받았는지 확인. 변경 전 2 failed, 변경 후 2 passed.
- 관련 Pilot 브라우저 회귀: 12 passed, 115 deselected (`logs/regression.txt`), `known_failures.py` 0 NEW. Pilot 셸 자산: 4 passed (`logs/shell.txt`). 로그는 위 X 세션의 `logs/`에 보관한다.
- `node --check`와 `git diff --check` 통과. 실제 로봇, 설치 앱, 네트워크 단절 때의 정지 readback 및 운영자 독회는 미확인이다.

## 수용 경계

LOCAL: Pilot 화면과 개발 서버 순서 확인. G2/G3: Pilot에서 실제 Console의 지도·SLAM·경로 화면까지 전체 시나리오를 다양한 폭과 상태에서 확인해야 한다. DEVICE/FIELD: 설치 후보 SHA와 실제 로봇의 정지 및 모드 상태, 지도 데이터의 출처·신선도, 운영자 수용을 별도로 확인해야 한다.
