# Fleet · AI · Discord 실제 연결과 D-720 숙고 확장

## 확인한 운영 증거

2026-10-12 현장 설치 source `19054491e240dfefc190dc84ec1d776c03e2b983`의
Discord transport에서 사용자가 새 메시지를 보냈다. 원문 message
`1559051332365586565`, Fleet request `dfe4028b0ffe3082938b4be5`이며 기명
`operator-livsbittt` 소유다. RECEIVED outbox는 SENT/1 attempt,
provider message `1559051335272235200`의 bot author와 원문 reference를
Discord에서 다시 읽어 확인했다. 보호 token은 출력·저장소에 기록하지 않았다.

기존 요청의 REVIEW 회신도 실제 provider reference를 검증했다. Qwen
`qwen3-vl:8b-instruct` digest `0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319`
실제 읽기 전용 모델 smoke는 약0.47초/32 tokens였다. 수동 시험임을 명시한
별도 회신 `1559052380056588309`의 실제 내용과 원문 reference를 읽었다.
이것은 새 자동 숙고 worker나 GLM 운영 연결의 증거가 아니다.

기존 AI situation observer heartbeat·profile은 실제 Fleet에서 읽었다.
간헐 timeout의 원인은 재현으로 특정하지 못했으며 diagnostic 변경은
method/route/class만 남기고 token/body/query/exception message를 기록하지 않는다.

## 이번 소스 검증

D-720은 별도 fleet_status/READ_ONLY_QUERY, 기존 domain digest 불변,
channel 범위 READ_ONLY tool, 원문 DB receipt equality, 고정 profile·
관측 generation, 호출 전 영속 예약, UNKNOWN no replay, 관측 freshness,
owner/profile/route revocation, known numeric cost 보존과 별도 billing evidence,
결과/outbox atomic commit, 취소·재시작 closure를 구현한다.

원격 RED로 결함을 먼저 확인했다. GREEN은 진단72, status68, jobs58,
codecs/launcher111, 기존 채널 포함65, owner/billing/source clocks18 tests의
선택 범위다. 서로 겹치므로 합산하지 않는다. known_failures의 NEW0를
확인했다. 최종 transport/installer/구조·통합 회귀와 독립 source 검토는
후속 실행 receipt로 이 문서를 갱신한다. 노트북 pytest는 실행하지 않았다.

## 아직 수용하지 않은 것

AI의 `rosy-deliberation` protected 계정에 대한 관리 권한은 이 세션에 없다.
reviewed source와 별도 key·host pin·SHA bundle·설치/복구 명령을 준비한다.
root 설치, 새 signed Fleet source 배포, 실제 새 요청의 자동 숙고 job,
조건부 GLM receipt와 원장/outbox/Discord 동일 reference까지 확인하기 전
운영 숙고 연결을 완료로 선언하지 않는다.

관측상 두 실제 CORE는 offline이었다. 물리 명령·E-stop 해제·학습·모델
자동 승격은 실행하지 않았다. 후속 평가/강화학습 개선에서는 단순 답글
전송이나 모델 자기평가를 성공 라벨로 사용하지 않고 실제 결과·부작용·
독립 검증과 결속해야 한다. 사용자 요청 순서대로 운영 연결 수용 뒤
기존 평가 기준·학습 파이프라인을 조사하고 개선한다.
