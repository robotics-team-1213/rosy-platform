# D-706 판정 후보와 전체 프로파일·독립 보정 입력 결속

**Status:** Accepted (2026-10-12, source contract)

D-705의 외부 승인 공급을 구현하기 전에 reasoning 후보의 내부 계약을 분리한다. 계산·재검증은 기존 Decision 순수 evaluation 소유자가 맡고, 영속 snapshot·신뢰 receipt·전환은 기존 `learning/registry/policy` 소유자가 맡는다. learning registry에서 운영 Decision을 import하지 않으며 검증된 자료를 공통 JSON과 신뢰 포트로 전달한다. 행동 PolicyArtifact의 stage나 promotion은 판정 모델 승인으로 사용하지 않는다. 새 서비스·CORE writer·SDK 공개 필드를 만들지 않는다(D-427·D-449).

후보는 하나의 정확한 ModelProfile, 한 domain의 fit/evaluation/training/reviewed_profile 원본과 재계산한 CalibrationArtifact를 포함한다. 역할·모델·adapter·capability·호출 예산·calibration revision을 포함한 전체 profile hash를 검증한다. 기존 독립 보정 계산과 split/lineage/금지 오류 검증을 재사용한다. 원본과 결과를 함께 seal하고 읽을 때 다시 계산해, hash를 다시 붙인 위조 PASS나 다른 profile/domain 결속도 거절한다.

후보 생성은 HOLD·FAIL·PASS_OFFLINE_ONLY를 그대로 보존하며 승인이나 현장 수용을 만들지 않는다. profile이 지원하는 다른 domain까지 보정됐다고 확장하지 않는다. 검수 이름과 hash는 출처 진위의 증거가 아니므로 다음 영속 승인 단계에서 별도의 신뢰된 receipt를 검증한다. 운영 current/previous 전환·CAS·복귀·사건 소유 revision 보존과 실제 품질/현장 수용은 별도다.

후속 구현과 검증 순서는 [프로파일 lifecycle 계획](../plans/2026-10-12-reasoning-profile-lifecycle.md)을 따른다.

후보 JSON과 입력은 각각 2 MiB 이내로 제한하며 모델 invocation의 16 KiB 제한과 혼용하지 않는다. 이 내부 소스 계약은 SDK wire나 runtime 활성화를 바꾸지 않는다. Decision은 기존 Fleet wheel/sdist에 포함되며 실제 설치 import closure를 확인한다.

기존 Model PC 도구 `tools/decision_calibration.py --candidate <input>`가 `{profile, calibration_input}`에서 후보를 실제 생산한다. `--from-feedback`을 함께 쓰면 기존 원장·검수 입력 결속을 먼저 수행한다. 비교 모드와는 배타적이며 offline PASS일 때만 exit 0, HOLD·FAIL은 후보를 보존하면서 exit 1이다. 모델·네트워크·장치 호출은 없다.
