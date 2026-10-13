# Fleet·Qwen 불일치와 GLM 재평가 구현 증거

- Source: `8709923045` / `feat/conditional-model-review`.
- Contract: D-679; 확률·모델 교체·운영 자동 처리 목표는 D-681.
- Remote integration: **149 passed, exit 0, NEW 0**.
- Log: `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/model-binding-green/run-1.txt`.

Qwen 기본 의견은 정상·위험·기권·만료·비용 불명 여부를 검사한다. 같은 사건에 검증된 Fleet 기준 선택이 있고 Qwen과 다르면 GLM 한 번의 비교 검토를 요청한다. 기존 의견 형식 오류/충돌/관측 부족의 두 번째 검토도 제한한다. 검토 완료는 HOLD이며 기존 원장은 정책 변경으로 cached 결과를 교차 사용하는 요청을 거부한다. 비교 기준이 없는 입력은 Fleet 선택을 추정하지 않는다. 기존 baseline 없는 입력의 digest는 유지한다.

고정 GLM 게이트웨이·namespace relay·OpenCode launcher의 가짜 전송/실제 benign process 시험을 통합했다. 고정 목적지·모델·도구 거부·응답 바인딩·usage·1회·시간·취소·환경 비상속을 확인한다. custom CLI 비용 0을 실제 비용으로 오인하지 않도록 launcher의 미검증 비용을 거부한다. Coding Plan 실제 비용은 미확인이다.

첫 통합 실행에서 `/proc` 존재 확인과 읽기 사이에 정상적으로 종료된 자식 때문에 실패한 시험을 고쳤다. 다음 실행에서 두 번째 HTTP 요청 거부가 연결 종료로 전달되는 경우를 시험이 처리하지 못한 경합을 고쳤다. 종료·재호출 거부 조건을 유지하고 최종 suite를 통과했다. 새 실패를 known_failures에 등록하지 않았다.

원격 실행기의 마지막 통합 실행은 자원 하한 미달 fallback 경고를 냈다. 최종 component 시험은 여유 확인된 AI PC에서 Fleet/Decision 144 passed, gateway 70 passed, launcher 46 passed/추가 비용 표식 13 passed였다. 이 수치는 범위가 겹치므로 합산하지 않는다. 자원 부족 상태의 통합 결과를 운영 지연·용량 증거로 사용하지 않는다.

**미확인:** 실제 Fleet 기준 선택 생산자 연결, 격리된 OpenCode SDK/설정/relay 실제 실행, 유료 GLM 호출, 영속한 첫 실제 호출 사용 표식, 판정 JSON 다음 버전·독립 calibration·운영 자동 처리, Jev/Laya 실제 어댑터 수용, 배포·Pinky 장치/현장 수용. 이 문서는 SOURCE/원격 논리 증거이며 실제 제공자·현장 PASS가 아니다.

독립 검토에서 upstream 모델/assistant 역할 검증 누락을 발견했다. 잘못된 모델·누락된 모델·다른 역할 회귀 3개를 RED로 확인한 뒤 결과 재작성 전에 거부하도록 수정했다. 최종 source와 149 passed 로그를 독립 검토자가 읽어 blocker 해소를 확인했다.
