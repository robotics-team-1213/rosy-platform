---
title: "Fleet 신원 조회 제한과 TLS 신원 불일치 구분"
date: "2026-11-23"
module: "Fleet enrolled TLS"
problem_type: runtime_error
component: deployment
severity: medium
symptoms:
  - "정상 TLS 연결에서 신원 조회가 429를 반환한 뒤 Fleet 자세 확정이 502로 실패했다."
root_cause: logic_error
resolution_type: code_fix
tags: ["fleet", "pinky", "tls", "rate-limit"]
---

# Fleet 신원 조회 제한과 TLS 신원 불일치 구분

Pinky 릴리스 `2026.11.23-230`에서 Fleet이 자세 확정을 요청할 때 정상 인증서와 호스트 이름으로 연결한 뒤에도 간헐적으로 `EnrollmentTlsError`가 발생했다. 같은 연결에서 공개 신원 조회의 200과 429를 관측했다.

## 원인과 수정

Fleet 등록 클라이언트는 인증 정보를 보내기 전에 대상의 공개 신원 응답을 검증한다. CORE는 이 신원 조회에 소스별 60초 슬라이딩 윈도를 적용한다. Fleet이 429 오류 본문을 `IdentitySnapshot`으로 읽으면 스키마 오류가 신원 불일치로 보인다.

Fleet은 먼저 상태 코드를 읽고 해당 목적지의 일반 신원 조회를 `Retry-After` 동안 유예한다. 신원 검증을 완료한 뒤에만 인증 정보를 보낸다. 자세 확정은 후보 조회와 결정 제출 단계에서 받은 429를 호출자에게 전달한다.

CORE가 알리는 60초는 실제로 다음 슬롯이 열리는 시각보다 길 수 있다. 정지와 취소는 Fleet의 로컬 유예 중에도 새 신원 조회를 한다. CORE가 그 조회를 거절하면 요청은 회신한 429로 끝난다. 이 구분은 서버의 제한과 TLS 검증을 유지하면서 일반 상태 폴링의 실패가 정지 요청에 추가 대기 시간을 부과하는 일을 막는다.

## 재확인과 현장 복구

- `test_enrolled_tls.py`는 일반 요청의 유예, 정지 경로의 재조회, 유예 뒤 잘못된 신원의 차단을 확인한다. `test_relocalize_routes.py`는 후보 조회와 결정 제출에서 429 및 재시도 시각 전달을 확인한다.
- 현장 재발 시 승인된 대상의 신원 응답 상태와 `Retry-After`를 먼저 확인한다. 429면 해당 Fleet 동작은 재시도 시각 뒤 다시 수행한다. 신원 불일치가 계속되면 등록된 CA·호스트 이름·로봇 번호를 점검한다. 현장 배포 후 재검증은 별도로 남아 있다.

관련 계약은 [D-565](../../adr/D-565-fleet-tls-re-enroll-after-renumber.md)와 [D-580](../../adr/D-580-site-roster-follows-fleet-enrollment.md)을 참조한다.
