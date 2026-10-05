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

`assess-pinky <revision>`은 hash-bound `rosy.pinky-offline-eval/1`의 m/s·rad/s
각각을 zero/train-constant 기준과 비교하고 reload·frame 수·명목 limit 위반을 검사한다.
기록된 CORE 속도는 expert intent가 미확인이므로 현재 gate는 reject를 유지한다.
Pinky 승격에는 정확히 하나의 bound 보고서가 필요하며 거절을 외부 signed pass로
덮어쓸 수 없다. idempotent 평가가 정책의 unregistered 단계를 바꾸지 않는다.

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
OMX sample body profile(Q6)의 시계·rad 목표·완료 상태·PNG와 wrapper 연결을 검사한다.
Pinky는 닫힌 원본 session/변환 metadata binding과 sidecar 시계/명령 의미를 검사한다.
Pilot은 본문 검증기가 없어 등록을 거부한다. 라벨/과제·MCAP 변환 진위 수용은 별도다.
승격과 이력 조회는 Dataset Episode profile·robot/environment와 정책의 일치를
같은 검증된 Episode 객체로 판정한다. 설치·camera/joint/runtime owner binding은 후속이다.
rollback/stop-readback,
owner binding/lease/generation/stale/HOLD, 실제 Fleet join·운영 배포는 후속이다.
torch/ROS/network/actuator는 사용하지 않는다. 모든 DB·산출물은 X에 둔다.

## 오프라인 Fleet receipt 연결

`python learning/registry/policy/fleet_join.py <episode-manifest.json> <receipt.json> <new-export.json>`
은 기존 D-18 `DeviceActionReceipt` validator(Pydantic)를 재사용하는 별도 도구다.
Registry 자체에는 새 import나 실행 권한을 추가하지 않는다. Episode 원본 파일의
SHA/bytes와 입력 manifest/receipt hash를 기록하고, 단일 action/attempt 및 device와
receipt.instance_id가 모두 일치할 때만 mission/step/request/epoch/generation을 연결한다.
키 없음·여러 키·불일치·terminal 결과 충돌은 binding=null의 unmatched로 남긴다.
Episode outcome evidence의 상대 경로는 원래 Episode root에 속하며 export 디렉터리의
파일로 해석하지 않는다. source archive는 Episode revision으로 별도 보존해야 한다.
출력은 같은 디렉터리의 임시 파일에 완전히 쓰고 fsync한 뒤, 배타적 hard link로
게시한다. 저장 실패나 게시 전 입력 변경은 최종 파일을 남기지 않으며, 경쟁
게시자의 파일은 덮어쓰지 않는다. 예외 처리 시 자기 임시 파일만 지운다. 프로세스가
강제 종료되면 임시 파일이 남을 수 있지만, 최종 경로에는 부분 JSON을 게시하지
않는다. hard link를 지원하지 않는 파일시스템에서는 게시를 거절한다. 이 동작은
전원 손실 뒤 디렉터리 메타데이터의 내구성이나 Fleet 수신 확인을 보장하지 않는다.
POSIX에서는 임시 파일의 소유자 전용 권한을 유지한다. 다른 계정의 receiver에
전달하려면 기존 운영 전달 경로에서 별도 읽기 권한과 수신 증거를 확인해야 한다.

task outcome/judge와 policy null을 보존한다. receipt.state=SUCCEEDED가 독립 과제
성공이나 policy 실행 증거를 만들지 않는다. 구조 검증·해시는 receipt 진위나 Fleet
수신 원장 readback을 증명하지 않는다. 운영 권한·승격·physical/sim receipt identity
수용은 별도다. 2026-10-04 실제 snapshot Episode10개는 모두 상관 키가 없었다.
따라서 실제 연결은 미실행이며 다음 recorder/export에서 기존 owner의 정확한 키를
보존해야 한다. `docs/validation/learning-fleet-export-2026-10-04.md` 참조.

OMX common_episode 변환의 `--owner-receipt <json>`을 goal마다 반복해 원본
goal UUID와 receipt를 연결할 수 있다. export는 OMX/Pinky profile validator를
실행하고 Pilot은 거절한다. OMX matched 결과는 별도 receipt의 전체 실행 identity와
journal/driver goal을 보존된 owner receipt와 다시 비교한다. profile 변경이나
같은 action/attempt의 다른 generation으로 우회하지 않는다. 구체 검증은
`docs/validation/omx-owner-receipt-provenance-2026-10-04.md` 참조.

`omx_policy_execution_v1`은 native 정책 실행의 설치 원본/intent/callback과 실제
owner API receipt를 보존하는 별도 evidence profile이다. Fleet export는 전용 body
validator를 호출하고 원본 receipt 전체와 다른 watermark/state/goal/journal을 거부한다.
정책 revision을 결과에 보존하지만 metadata-only 관측은 demonstration이나 training
GT가 아니다. DatasetStore/승격 호환 매핑은 확대하지 않는다. 파일 해시 검증은
Fleet 수신 원장·receipt 인증·실제 추론/task/physical 결과를 증명하지 않는다.
