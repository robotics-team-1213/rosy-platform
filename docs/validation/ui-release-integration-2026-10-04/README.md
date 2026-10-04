# 웹 앱 통합·배포 검증 (2026-10-04)

## 범위와 결정

사용자 요청에 따라 D-439 공용 디자인 적용을 최신 D-427 소스 구조에 통합하고,
기존 설치를 유지하는 앱 업데이트와 정식 이미지 배포를 진행한다.
화면은 로봇 진입 → 운용·카메라 → 준비·설치·정비 → Fleet → 게임·도구 순서로 점검한다.
디자인·연결·발열 대응의 근거는 D-439와 D-432이며, 로봇과 관제 배포는 각각 D-225와 D-301/D-441을 따른다.

## 통합에서 수정한 문제

- Pilot Android 원본과 Gradle 입력을 `middleware/ui/pilot/android` 및 실제 공용 자산 경로로 이동했다.
- 공용 토큰 registry와 운영 도구·모델 코드 후보의 의존 경로를 D-427 구조에 맞췄다.
- Fleet의 신호 감독과 stuck resolver를 각각 시작·취소하는 수명주기를 보존하고, UI 요청 없이 실제 worker 두 개가 함께 실행·종료되는 검사로 확인했다.
- 구형 Site updater 대신 최신 main의 검증된 descendant·이미지 식별·복구 journal·rollback·prune fence 구현을 보존했다.
- CI의 Gazebo 임시 `COLCON_IGNORE`를 빌드 후 제거해 소스 package inventory를 원상 복구한다.
- 실제 OpenCV 4.6의 ArUco 생성·검출 API를 지원한다. 영상 경계의 subpixel 보정창을 3으로 제한해 재현 오차를 5.363mm에서 3.436mm로 줄였다. 기존 5mm/4mm 및 각도 기준은 유지한다.
- Android CI는 Cam과 Pilot의 JVM 검사를 각각 실행하며 공용 입력 변경에도 동작한다.

Fleet의 실제 합계 30063줄은 두 부모의 기능을 보존한 결과다. 추가 257줄의
신호 감독·정지 transport·소유자 복구 등 담당 모듈을 독립 계수했다.
구조 분리 과제와 기존 +150 허용치는 유지하며 파일별 상한을 완화하지 않는다.

## 확인된 증거

| 항목 | 결과 |
|---|---|
| migration/harness/구조 재검사 | 110 PASS, 기존 staleness 경고 12 |
| 나머지 quick gate 검사 | 370 PASS, Linux 전용 2 SKIP |
| 공용 토큰·registry 실패 범위 재검사 | 3 PASS |
| Pilot JVM | 30 PASS, 실패·제외 0 |
| Pilot APK 자산 | 공용 20개와 Pilot 전체 29개가 현재 원본과 일치 |
| Cam JVM | 341 PASS, 실패·제외 0 |
| ArUco 실제 OpenCV 5.0 | 45 PASS, 제외 0 |
| ArUco 실제 Ubuntu OpenCV 4.6 | 동일 45 PASS, 제외 0 |
| 기존 Android 서명 | 두 설치본과 새 APK 인증서 SHA-256 일치 |
| 무선 ADB 업데이트 | Pilot과 Cam 모두 `install -r` 성공, 기존 앱을 삭제하지 않음 |
| 독립 검토 | Pilot/Fleet worker SPEC·QUALITY, ArUco SPEC·QUALITY, Site 원본 보존 및 scoped 안전 검토 PASS |

첫 실패와 수정 후 재검사 로그를 모두 보존한다. Windows의 Linux 전용 updater
symlink/flock/systemd 제외는 Linux 실행·현장 검증으로 간주하지 않는다.

## 아직 필요한 확인

### 기존 커밋의 안전 검토 기록

이미 작성된 commit SHA `7e34baacebc02dd6103dbdd17c5e861b92a02945`와
commit SHA `a4caeed0f5119df17f138203cd6e01eb373da671`은 안전 trailer가 없었다.
독립 검토자 `Codex /root/pilot_review`가 실제 커밋과 현재 이동된 소스를
대조해 각각 DNS-SD TXT/제한된 개발 접속/TLS/SSH 보호와 신선한 heartbeat의
REST fallback을 확인했다. 펌웨어 interlock·기존 dispatch·CORE 최종 명령 권한은
유지된다. D-430 역사 예외는 위 두 전체 SHA에만 적용한다.
기존 커밋을 수정하지 않으며 새로운 안전 변경의 독립 검토 의무는 유지한다.

원격 main SHA/CI, 서명된 정식 후보의 배포 및 실제 실행 SHA,
태블릿·Cam 최종 화면/설정 유지, 순차 화면 점검 결과를 이 기록에 추가한다.
켜진 로봇의 mDNS 광고는 확인했으나 SSH 경로는 별도로 확인 중이다.
꺼진 로봇의 배포·동작은 미검증이다. 정지 해제나 구동 명령으로 배포 검사를 통과시키지 않는다.

### 추가 병합과 검색 진단 (2026-10-04)

- 전원·배터리·health·bridge 영향 범위 7개 파일: 225 PASS, 7.80초. SDK는 소스 wheel을
  X 드라이브의 검증 전용 경로에 설치해 사용했다.
- 모델 fingerprint metadata 수정: 기존 Linux 실패 4건과 새 경계 4건을 합쳐 8 PASS,
  31 deselected, 82.63초. 전체 모델 suite 재실행 결과로 주장하지 않는다.
- core_features 독립 집계: integration 부모 12662/73파일, main 부모 12701/73파일,
  병합 12723/73파일. +61은 기존 전원 소유의 변경이고 main 대비 +22는 D-442 command
  소유권 검사를 보존한 차이다. 파일 상한과 공통 +150 허용치는 유지한다.
- 독립 검토자 Codex /root/pilot_review: 추가 전원 정책 SPEC·Safety PASS 및 위 집계 확인.
- 실제 태블릿에서 native NSD 고착을 확인했다. Pilot만 재시작한 후 현재 로봇 광고가
  IPv4로 154 ms에 해석돼 1대 목록과 활성 연결 버튼을 확인했다. 검색 복구 증거이며
  CORE 연결·장비 배포·물리 동작 수락을 대신하지 않는다. D-432의 앱 내부 복구는 별도
  구현과 자식 종료·재바인딩 검증을 진행한다.

### 푸시 검사와 실제 네트워크 경계

main에 통합 commit SHA `6a549b980`와 provenance 표기 수정 commit SHA `1eb219940`를
fast-forward로 반영했다. 첫 pre-push는 461 PASS, 2 Linux SKIP였고 공개 커밋 SHA 네 줄을
high-entropy-token으로 판단한 한 검사가 실패했다. SHA에 commit revision 문맥을 추가한 뒤
그 실패 검사만 재실행해 1 PASS, 94.16초를 확인했다. 검사기를 완화하지 않았다.

모델 PC·관제 PC·같은 Wi-Fi의 태블릿에서 광고 주소의 SSH 연결을 확인했으나 현재는
시간 초과 또는 네트워크 경로 오류였다. 단발성 hostname 응답을 안정된 배포 경로로
기록하지 않는다. 로봇 배포는 접속·장비 식별·ABI·유지보수 전제가 충족된 후 진행한다.

Cam 기존 설정과 실제 3 fps 송출을 확인했다. 실제 캡처의 preview는 black였으며 원인은
  미확인이다. 새 진단 접힘 UI의 기본/펼침 상태와 영상 보기 검증은 별도로 진행한다.

### Android 최종 소스와 실기 관측

Pilot 기능 소스 6개 파일의 독립 SPEC·Safety·QUALITY PASS, JVM 46 PASS, APK 자산
20개 공용/29개 Pilot 일치, 기존 서명과 설치 APK SHA 일치를 확인했다. 실제 전용 검색 자식
장애 후 주 프로세스 PID 유지·새 자식 PID·새 IPv4 resolve·로봇 목록 복구를 확인했다.
연속 '다시 찾기' 두 번, background 자식 정리, resume 재검색도 확인했다. 로봇을
선택하거나 제어 명령을 보내지 않았다. 상세 로그·사진·개인 주소는 X 드라이브에 보관한다.

Cam 진단 접힘 UI는 JVM 341 PASS·APK 빌드 성공·동일 서명이며 업데이트 전후 설정
파일 SHA-256이 같다. 새 카메라 시작 후 실제 preview에서 경기장 전체가 표시되는 것을
직접 확인했다. 기존 black 캡처의 근본 원인은 확정하지 않았다. 자연 발열 40.1°C에서
경고와 1.5 fps 송출을 관측했다. 관제 Vision의 runtime debug frame:read lease를 사용한
두 HTTPS 프레임은 200/200, sequence 94→100, age 335→184 ms였다. 일반 operator
인증 API 검증과 구분하며 기존 CA 검증을 유지했다. 수신기의 기존 실행 SHA는 이번
소스 SHA와 다르므로 새 사이트 배포 수락으로 주장하지 않는다.
