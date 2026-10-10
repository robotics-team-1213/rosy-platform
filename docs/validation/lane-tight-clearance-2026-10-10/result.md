# D-617 앞/측면 조향 여유 적용 및 장기 LOST 사례

## 적용과 시험

- SOURCE: 앞쪽 조기 pivot 기준은 몸 앞끝 + 0.02m, 측면 출구는 몸 반폭 + 0.05m. 거부한 출구의 기억·pivot latch 제거. API/schema, 최종 CORE 제동, IR, 횡단보도 보호는 변경하지 않았다.
- 시험 PC: 관련 원격 회귀 112 passed, 설치 base 위 앞쪽/기억 수정 42 passed, 측면 5cm 포함 최종 설치 candidate 43 passed. 각 로그 `known_failures.py`: 0 NEW.
- signed delta DEVICE: 두 장치 2026.10.10-128 → 130 → 131. 실제 설치 파일과 git blob의 sha256을 대조했다. 최종 파일 sha256 접두사 `c8f7bb524805`; 최종 설치 candidate commit `2cac6b774`는 기존 설치본 위에 이번 변경만 적용한 브랜치다. main의 다른 미배포 제품 변경을 함께 보내지 않았다.
- source 통합 첫 gate: 4,233 passed, 164 skipped, 1 NEW. peer 문서의 commit 해시가 secret scanner에 걸려 이 회차는 착지하지 않았다. peer 수정 후 재검사에서 4,235 passed, 164 skipped, 62 subtests 및 capture 9 passed, 0 NEW를 확인했다. lint 0 errors, 25 warnings. commit `75335cf06d`를 로컬 main에 착지했다. 원격 CI나 실물 주행 합격 증거는 아니다.
- SPEED CONFIG: 사용자 선택에 따라 두 장치 cruise_speed 0.10 → 0.08m/s, max_linear 0.10m/s 유지. 최초 확인한 0.04m/s의 2배다. 기존 설정 백업은 장치 내부 0600으로 보존했고 다른 overlay 키가 그대로인 것을 assert로 확인했다. 두 CORE 재시작 성공(active), 10:01:14 UTC 설정 재읽기 0.08과 API IDLE/OFF·velocity 0을 확인했다. v2 keeper receipt도 최신이었다. 두 인증 세션 logout 204. 이 설정 적용으로 주행 세션을 다시 시작하지 않았다.

## 실제 관측

- 09:42 UTC 두 장치의 IDLE·실측 velocity 0·E-Stop false를 읽고 감독 전경 시험 세션을 시작했다. v2 keeper receipt를 확인했다.
- 9dfk: TRACKING 전진 후 몸 gap 0.0186–0.0225m에서 `obstacle_ahead`로 CORE 정지. 2회 back-off 뒤 `WAITING_CONSOLE`. 먼 물체를 보고 미리 돌아야만 하는 조건을 제거했지만 장애물 정지 자체는 남았다.
- 8kcn: 20cm 측면 기준 때 `drivable_closed`·장기 LOST. 131 적용 후 LiDAR 측면 0.134m에서 `drivable_centre`가 다시 나오고 실제 console에서 LOST → TRACKING 복귀(09:47:43)를 확인했다. 곧 camera/IR stale과 LOST가 다시 나타나 반복 문제가 모두 해결됐다고 판정하지 않는다.
- 09:47:45(8kcn), 09:47:48(9dfk) mode OFF를 읽어 전경 세션이 종료됐다. 자동 재무장하지 않았다. OFF 명령의 외부 주체는 이 점검에서 확정하지 않았다.
- 종료 helper의 `release-hold --json`이 설치 CLI에서 거부돼 자동 업데이트 hold가 남은 것을 발견했다. 지원하는 `release-hold`로 두 장치 모두 `released: true`를 확인했다. token logout은 두 장치 모두 204였다.

## 로그와 남은 범위

원본과 분석은 `X:/DevTemp/lane-pair-analysis/`에 있다. `9dfk-d617-console.log`, `8kcn-d617-console.log`, 앞 600초 bag JSON, keeper debug, 상부 사진을 보존했다. Pilot 녹화 `20261010T094207Z_rosy_41`, `20261010T094208Z_rosy_40`는 카메라 재시작 때 각각 약 213초, 234초에서 종료돼 이후 콘솔 구간 전체와 일치하지 않는다. 녹화 자동 이어쓰기 검증은 없다.

현장 Fleet container에서 D-610 사례 모듈이 미설치인 것을 확인했다. 기존 stuck 로그와 소스의 사례 저장 구현을 구분한다. 장기 LOST 처리·기록 보강 순서는 `docs/plans/2026-10-10-long-camera-loss-cases.md`에 있다.

변경 속도의 실물 주행, 비제로 회전의 5초 진전 감지, 동일 출발점의 단독/동시 비교, 8kcn wheel/odom 응답 원인은 아직 완료하지 않았다. v2 실제 수신·설치와 보호 정지 증거를 한 바퀴 주행 합격으로 부르지 않는다.
