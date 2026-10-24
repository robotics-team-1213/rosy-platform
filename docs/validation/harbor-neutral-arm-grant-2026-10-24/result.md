# D-856 중립 팔 grant 모델 검증

API v1.303의 비활성 DTO 등록과 기존 Action/stop DTO 이동을 검증했다. 중립 팔 접수·실행·물리 자원 종료·Harbor 업무 완료의 증거는 아니다.

## 소스와 시험

RED commit `93ec6212ea`: 신규 모델이 없어 공식 원격 31 failed였다.

GREEN commit `1258314f516a74cfc8b756603df9681c028db515`: 공식 원격 runner에서 **1385 passed, skip0, 2 warnings, 0 NEW/known/flaky**를 확인했다. 로그는 저장소 밖 `C:/Users/SERIGGG/AppData/Local/Temp/rosy-neutral-arm-grant-green/run-1.txt`에 보존했다. 새 grant의 strict/closed/frozen·distinct identity·aware expiry, foundation 전체, 기존 protocol/Action API/store/stop/Cell runner/receipt, Fleet step 경계와 API version 소비자, module architecture를 실행했다.

기존 device Action/stop DTO 14개의 AST는 RED 기준과 이동 후 동일하다. canonical import와 leaf의 클래스 identity·JSON schema 생성도 회귀했다. JSON schema 전체의 전후 문서 비교를 수행했다는 주장은 아니다. 독립 계약 검토에서 물리 payload·envelope·기존 runtime 거절 유지와 DTO 이동의 material finding은 없었다.

`size_range`와 `safety_review`는 commit `453ec1b553..1258314f51`의 두 커밋을 통과했다. schemas facade는 1142→811줄로 줄이고 ratchet도 낮췄다. 현재 manifest에서 이동한 DTO 경로는 safety-tagged 경로가 아니므로 이 변경에는 필수 trailer 조건이 적용되지 않는다.

## 권한과 한계

owner parser·phase/direct-driver kind sets·UDS v1/v2·Fleet step registry가 ARM_TRANSFER를 계속 거절하는 회귀를 포함했다. 새 모델의 생성이나 올바른 digest는 승인·서명·설치 기하 검증·실행 권한을 부여하지 않는다.

실제 grant 발행, owner capability와 phase/recovery 연결, legacy provenance migration, 모든 claim 해제 입구의 물리 종료 검증, simulation HTTP와 Harbor CargoMove 변환은 후속이다. 선행 FULL의 충전 조회 타임아웃은 이 집중 회귀로 해소됐다고 기록하지 않는다. 실물 실행·배포·push는 수행하지 않았다.

CE: 해당 없음 — 기능 추가와 DTO 이동의 판단 근거는 계약·설계·시험에 남는다.
