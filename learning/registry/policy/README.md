# 정책 metadata 원장

D-449 Proposed의 offline 정책 원장이다. SQLite BEGIN IMMEDIATE 트랜잭션,
FULL synchronous, 파일 snapshot, canonical event hash chain과 단계 CAS를 사용한다.
register는 실제 policy 파일/정규화/평가 bytes를 다시 검증해 원장 내부로 복사한다.
source 변경은 보존본에 영향을 주지 않고 같은 revision 재등록은 이력을 늘리지 않는다.
파일·단계·이력 손상은 다음 조회/변경에서도 거절한다. 초기 snapshot 후 DB commit
전 실패하면 orphan snapshot을 재검증해 재등록할 수 있다.

```text
python learning/registry/policy/registry.py --root <registry-on-X> register <ACT-run>
python learning/registry/policy/registry.py --root <registry-on-X> assess-act <policy-revision>
python learning/registry/policy/registry.py --root <registry-on-X> show <policy-revision>
python learning/registry/policy/registry.py --root <registry-on-X> history
```

assess-act는 artifact에 hash로 묶인 원본 offline-report의 metrics로 연구 조건을
재계산한다. reported pass를 그대로 수용하지 않는다. 같은 validator/result/report의
재평가는 idempotent다. reject/offline_only는 단계 변경이 아니며 원장은 unregistered다.
마지막 단계는 metadata 승격 상태이고 owner의 실행 권한이 아니다.

Python API promote는 인접 단계 PromotionRecord와 실제 report JSON의
policy_revision/kind/verdict를 검증한다. 모든 check에는 trusted principal의
HMAC-SHA256 receipt가 필요하며, 설치 trust는 principal별 key(bytes)와 allowed
kinds(set)를 별도 주입한다(key 최소 32 bytes). receipt payload는 promotion_revision/policy_revision/
kind/report_sha256/verdict=pass를 정확히 묶고 signature는 payload sorted keys,
compact UTF-8 JSON에 대한 HMAC이다. authority가 있으면 operating_authority
receipt와 policy-bound pass 보고서를 추가 요구한다. trust keys는 원장에 저장하지
않는다. 운영 verifier나 승인 키를 설치하지 않았고 CLI에는 promote 명령이 없다.
테스트의 signed pass 보고서는 합성 fixture이며 실제 승격/평가 수용 증거가 아니다.
bound ACT reject는 외부 signed pass 주장으로도 덮어쓸 수 없다.

서명은 설정된 verifier가 해당 bytes를 인정했다는 뜻이며 독립 판정의 정확성을
자동 증명하지 않는다. trust 설정을 누가 승인하는지와 보고서 생성기는 후속이다.
hash chain은 보통의 손상을 감지하지만 전체 DB를 다시 쓰는 공격에 대한 외부
anchor/서명이 아니다. history 재독출은 파일/chain/단계를 확인하며 과거 receipt의
현재 key 신뢰 수용을 재판정하는 owner loader가 아니다.

policy snapshot은 가중치·config·정규화·평가를 보존한다. dataset_store.py는
DatasetManifest·실제 공통 Episode 목록과 그 source/stream/evidence 파일의 선언된
dataset files 포함·SHA/bytes를 검사하고 immutable snapshot/SQLite에 등록한다.
`python learning/registry/policy/dataset_store.py --root <registry>/datasets <dataset-root>`로
등록한다. promote와 과거 promote 이력 조회는 모든 policy dataset revision이
등록되고 실제 파일이 온전해야 한다. register/assessment는 unregistered 연구
metadata 보존이므로 아직 dataset이 없더라도 실행할 수 있다.
원본 sample body profile 검증(Q6)이나 라벨/과제 진위 수용을 대신하지 않는다.
rollback/stop-readback,
owner binding/lease/generation/stale/HOLD, Fleet join·운영 배포는 후속이다.
torch/ROS/network/actuator는 사용하지 않는다. 모든 DB·산출물은 X에 둔다.
