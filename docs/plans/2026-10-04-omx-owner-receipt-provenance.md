# OMX owner receipt provenance implementation plan

**Goal:** 실제 원본 goal UUID와 owner receipt를 대조해 공통 Episode의 Action/attempt를 보존한다.
**Architecture:** 기존 녹화기/owner/safety를 바꾸지 않고 오프라인 common_episode 변환기에 receipt 입력을 추가한다. contracts/learning의 stdlib profile validator가 sample goal 전체와 동일 실행 identity를 다시 검증한다. receipt 인증과 policy 실행 판정은 별도다.
**Tech Stack:** Python, 기존 D-18 Pydantic receipt schema, stdlib artifact 검증.

1. RED: receipt 없는 nonempty correlations 거절 테스트와 단일/다중 goal exact coverage,
   instance/attempt/generation 불일치·부분 coverage·source 손상 거절 테스트를 추가한다.
2. contracts OMX profile에 goal-to-receipt provenance 검사와 source receipt byte refs를 추가한다.
   legacy receipt 없는 녹화는 empty correlations를 유지한다. Action 결과/task/policy는 추정하지 않는다.
3. common_episode.convert(..., owner_receipts=...)는 기존 wire parser로 입력을 검증하고
   원래 receipt bytes를 별도 source로 복사한다. 모든 sample goal을 정확히 포함하는
   동일 mission/step/action/attempt/workcell/instance/request/epoch/generation/journal만 허용한다.
4. 공통 profile·변환·Fleet join 회귀와 독립 리뷰를 실행한다. 실제10Episode는 수정하지 않는다.
5. 계약 wheel 버전과 문서/보고서를 보강한다. 실제 owner journal 수집·SIM 실행/물리 수용은 후속이다.

기존 root/frozen OMX recorder에 새 코드나 기능을 추가하지 않으며 D-427 이동을 유지한다.
여러 Action이 섞인 녹화는 하나의 pair로 축약하지 않는다. 해당 녹화 분할/다중 pair 계약은
후속 설계가 필요하다. 현재 source로 검증되지 않은 정책 revision을 채우지 않는다.
