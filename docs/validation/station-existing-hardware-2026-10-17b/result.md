# 기존 카메라·Fleet 위치 재확인

2026-10-17 KST. [앞선 확인](../station-existing-hardware-2026-10-17/result.md)의 후속 읽기 전용 점검이다. 기존 Fleet PC에 고정 호스트 검증·비대화형 키 인증으로 접속했다. 장치 설정, 등록, 서비스 재시작, 버스 쓰기, 모터 활성화와 이동은 수행하지 않았다.

## 실제 재관측

카메라 조회 원본 UTC seconds는 `1792169514.8381288`이다. 기존 상부·전면 producer와 viewer/readiness 서비스는 모두 active였다. 두 JPEG GET은 HTTP 200, image/jpeg이며 각각 6,169/113,734 bytes였다.

| 대상 | 기존 viewer의 이번 판정 | 해석 |
|---|---|---|
| 상부 | fresh, source age 약 0.599초, mean intensity 1.0833, dark fraction 0.999948, UNDEREXPOSED, usable=false | 영상 수신은 되지만 현재 밝기 조건에서 위치 추정에 사용할 수 있다는 근거가 없다 |
| 전면 | fresh, source age 약 0.197초, NORMAL, usable=true | photometric 검사 통과이며 위치·시야·정밀도 수용은 별도다 |
| 암 관절 viewer | sequence 19, source stamp `1792163979.6385915`, 약 5,535초 전, fresh=false | 앞선 유한 시간 관측 이후 실시간 관절 피드가 지속된 것은 아니다 |

기존 Fleet/Vision/proxy 컨테이너는 healthy였다. 실제 Fleet DB를 파일 소유 UID로 열고 `mode=ro`와 `PRAGMA query_only=ON`으로 필요한 열만 조회했다. 자격 증명을 읽거나 복호화하지 않았다. DB 조회 시각은 `1792169573.8094068`이다.

| 대상 | 이번 읽기 결과 |
|---|---|
| `rosy_40` | 마지막 관측 `1791801832.0214977`, source `ceiling_north`, 등록 `needs_new_code` |
| `rosy_41` | 마지막 관측 `1791801821.8733447`, source `ceiling_north`, 등록 `needs_new_code` |
| 지도 기록 | 최신 저장 version 5; 이 조회만으로 새 활성화나 현재 로봇 위치를 주장하지 않는다 |
| 실제 Vision 설정 | source `ceiling_north`, map `map_v2_fleet`, calibration revision `map_v2_fleet`, processor `aruco-opencv-4.12`, `field_boundary`, 대상 두 로봇 |

기존 관제 위치 source와 OMX USB 카메라 viewer를 같은 보정 source로 취급하지 않는다. 위치는 이번에도 갱신되지 않았다. Fleet PC·암·카메라의 연결 부재로 확대 해석하지 않는다.

## 현장 확인과 다음 경계

사용자는 상부 카메라의 가림·방향·조명과 현장 상태를 담당자가 나중에 확인할 수 있다고 답했다. 실제 확인 완료 또는 물리 구동 시 현장 입회로 간주하지 않는다. 현장 확인 이후 현재 지도 관측과 정상 등록, 카메라 보정·착좌·충전/BMS·정지 계측의 실기 프로필을 확인해야 자동 접안/충전 시험으로 진행할 수 있다.

소프트웨어 운행 한계 구현은 계속할 수 있다. 이번 기록은 실제 연결·현재 영상 상태·관제 저장 위치의 시각을 재확인한 증거이며, 자동 접안이나 DEVICE/FIELD 수용 증거가 아니다. 전체 목표는 ACTIVE다.
