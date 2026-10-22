# 현재 운영 버전 기반 모터 상태 연결

기존 구현은 `feat/omx-safe-native-teleop`에 보존했다. 동일한 승인된 작업 공간에서 현재 운영 commit `3cdfd40ac2abb05e0630a49a09e762d8f86472aa`를 기준으로 `feat/omx-motor-health-runtime`을 만들고 모터 상태 기능만 옮겼다. 운영 인증·D-837 위치/카메라 관측·Learning 변경을 되돌리지 않았다. 이 기록은 배포 완료 증거가 아니다.

## 연결한 경로

기존 단일 버스 소유자인 수동 관측기가 이미 읽는 0..146 레지스터 블록에서 PWM·온도·전압·설정 한계·하드웨어 오류·토크 상태를 해석한다. 선택적 명시 경로에 원자적 스냅샷을 기록하고, 기존 bridge가 출처별 인증으로 Fleet에 전달한다. CORE 읽기 전용 API와 Fleet 로봇별 캐시도 같은 DTO를 사용한다. 통합 관제 요약, 선택 로봇 상세, 로봇 자체 콘솔, Cell의 팔별 상세가 공용 표시기를 사용한다.

A12의 오류 32 때문에 위치 관측이 시작 전에 끝나는 경우에도 고장 기록을 전송한다. `positions:null`은 등록된 소유자·관절에 결속된 종료/고장 기록에서만 허용하고 위치를 생성하지 않는다. 모터 측정 나이와 종료 사건 시각은 별개다. 시계 역행·비정상 시각·통신 지연이 실시간 상태를 만들지 않는다. 실제 오류 신원이 있으면 고장 모터 수·팔 이름·ID·오류 코드를 표시한다.

일반 SDK 경로는 그대로 엄격하다. 읽기 전용 진단의 선택적 경로에서만 model1060의 COMM_SUCCESS/Alert128 응답을 하드웨어 오류 레지스터의 실제 비영 값과 함께 허용한다. model1200의 경고·다른 통신/명령 오류는 거절한다. 허용된 패킷은 기존 PING과 전체 블록 READ뿐이다. 모터 설정·토크 ON·고장 해제·재부팅은 추가하지 않았다.

## 실행 인수와 배포 조건

관측기에는 각각 `--health-file /absolute/private/arm_a.json --health-owner arm_a`, `--health-file /absolute/private/arm_b.json --health-owner arm_b`를 명시한다. bridge에는 등록 출처별 `--arm-health-file SOURCE_A=/absolute/private/arm_a.json`과 `--arm-health-file SOURCE_B=/absolute/private/arm_b.json`을 명시한다. 실제 출처·USB·계정·인증값은 비공개 운영 설정에 둔다. 건강 파일의 부모 디렉터리는 해당 서비스 소유자만 쓸 수 있어야 한다.

기존 unit은 이 선택적 인수를 전달하지 않으므로 파일 환경 변수만 추가해서는 활성화되지 않는다. 실제 적용에는 고정 소스 릴리스와 foundation 모듈 경로, per-arm service drop-in의 명시 인수, 관측기보다 먼저 준비된 bridge가 필요하다. observer는 Restart=no를 유지한다. 두 번째 직렬 포트 독자를 시작하지 않는다.

운영 Fleet 이미지는 [배포 절차](../../deploy/site/README.md)의 D-441에 따라 정확한 main 커밋의 CI 통과·서명 후보 검증 후 교체한다. 현재 소스의 공개 게시·CI·서명·운영 교체·실측 수용은 별도 단계다. 원래 실행 중인 observer/bridge 및 이미지와 A12 fault marker는 이 검증 중 변경하지 않았다.

## 원격 검증

- commit `79a11a4a54b956344b47bc81fd968fbc26565653`: 공식 모델 PC의 producer·observer·bridge·출처 인증 ingest·DTO·실제 TLS Vision 파이프라인 관련 8개 suite, 154 passed/skip0/NEW0. `rosy-safe-native-20261022/passive-clock-green/run-1.txt`.
- `8e8861fc39`: 공식 원격 UI 및 기존 D-837 관측 회귀 15 passed/skip0. `omx-motor-ui-current-green/run-1.txt`.
- `921062fb1c`: 공용 자산 설치·색상·부품·패널·기존 Node 계약 84 passed/skip0. `omx-motor-ui-current-contracts/run-1.txt`.
- `5a9b17c5d9`: 최종 관절 이름·오류 신원 유지·Cell 두 폭의 집중 검증 3 passed/skip0. 후속 `78a7c8b7bf`는 캡처 표시 위치만 바꾸고 1개 브라우저 시험 통과. 모두 NEW0. 수치는 겹치므로 합산하지 않는다.
- 새 모터 JS/CSS·Cell adapter에 대한 UI 기계 검출 결과 `[]`, exit0. 390/1366 폭의 LOCAL 합성 화면을 육안 확인했다. 화면 캡처는 실제 모터나 현장 수용의 증거가 아니다.
- 확대 선택에서 Fleet 6189 passed/344 skipped와 함께 문서별 import·공용 CSS 분류 2건 실패를 발견했다. `a94cf83b6e`에서 새 모터 adapter와 index 전용 공용 시트를 정확한 소유 목록에 추가하고, 포커스 카드 배치를 독립 helper로 분리했다. 후속 Node·두 포커스 브라우저·문서/CSS 계약 7 passed/skip0/NEW0. 기존 roster 크기는 709→694로 줄였고 Fleet 자원 cleanup도 기존 크기를 유지한다.

독립 읽기 전용 검토자는 최종 `79a11a4a54`의 레지스터 해석·Alert 허용 범위·단일 소유자·파일·출처 인증·신원·나이 계산·Cell 표시를 검토했고 지원되는 차단 결함이 남지 않았다고 판정했다. 하드웨어 안전 인증이나 운영 적용 검토가 아니다.

공용 foundation 변경으로 영향 선택기는 FULL을 요구했다. 원격 `--affected-json`은 해당 모듈과 관련 guard의 확대 선택이며 GitHub FULL을 대신하지 않는다. 현재 원격 선택 실행과 별도로 공개 게시 후 정확한 main SHA의 전체 CI를 요구한다. 앞선 `921062fb1c` 집중 backend 실행은 시험의 물리 폴더 경로를 공개 import 경로로 오인한 collection 오류로 실패했고, `42b4c99958`에서 기존 설치 식별자 `fleet.server.console_view`로 수정했다. 해당 실패를 통과 근거에 포함하지 않는다.

물리 과부하 원인과 모터 무손상은 입증하지 않았다. 이 변경은 오류를 관측·표시하며 A12 오류를 해제하지 않는다.
