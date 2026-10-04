# 고정 평가 세트의 내용 검증과 학습 혼입 거절

2026-10-04, 기준 checkout `3c0a9c141`. D-379의 학습·평가 세션 비겹침 보호를 보강했다.
기존 평가/학습 데이터와 gate 기준은 변경하지 않았다.

## 발견과 수정

build.read_eval_set은 --exclude-eval 폴더의 purpose와 manifest 세션 목록만 읽었다.
폴더의 내용 SHA가 버전 이름과 같은지는 검사하지 않아 manifest의 세션을 삭제하면
학습·평가 비겹침 검사에서 원래 heldout 세션이 빠질 수 있었다.
이미지·마스크 변경이나 추가 파일도 이 경로에서 감지하지 못했다.

네 가지 내용 변경을 기존 코드 RED4로 재현했다. 별도로 2세션 CVAT 입력에
원래 heldout 세션을 포함하고 평가 manifest 세션을 삭제했을 때 기존 builder가
거절하지 않는 것도 기존 HEAD bytes를 X에서 실행해 RED1로 확인했다.
첫 1세션 재현은 뒤의 최소 세션 규칙에 걸렸으므로 이를 혼입 성공 증거로 사용하지 않았다.

새 경로는 파싱한 manifest bytes를 보존하고, 폴더 전체 content_sha가 버전 이름과
일치하는지 확인한다. manifest 구성 요소의 hash는 파싱한 bytes에서 직접 계산한다.
내용 계산 후 manifest bytes도 처음 읽은 값과 비교한다.
파일 읽기 오류와 hash/manifest 변경은 BuildError로 거절하며 학습 출력 작성 전에 실패한다.
읽기 도중 manifest가 바뀌는 회귀도 추가했다. 신뢰하는 immutable store의 무결성 검사이며
파일 시스템 잠금·사용자 인증이나 검사 이후 무변경까지 보장하는 기능은 아니다.

독립 검토는 최초의 앞뒤 bytes 비교만으로는 A→B→A 변경이 통과하는 문제를 발견했다.
이를 추가 RED1로 재현한 뒤 위 captured bytes 직접 hashing으로 수정했다.
일반 content_sha 호출의 계산 규칙과 기존 builder 버전은 바꾸지 않았다.

## 실행 근거

- 평가/build/catalog-store 관련 53 pass / 1 skip.
- `X:/DevTemp/rosy-learning-audit-20261004/eval-exclusion-integrity-v1`에 기존·수정 source,
  정상 2프레임 host fixture와 별도 변조 사본, result.json을 보존했다.
- 정상 사본의 내용 hash와 버전 이름이 일치하고 세션 목록을 읽었다.
  별도 사본의 manifest 세션 삭제는 content hash 오류로 거절됐다. 원래 fixture는 그대로다.
- 정상 fixture SHA-256: `4575d65af427db8bee9ade2c8c4fa72a5db11d247bf2500eb09ae6fb68a99333`.
- 최종 source SHA-256: `a14e3549388bbaf9891b96dce39c1ea84e7df34169a5ebde38bf5d26ae7eeefa`.
- 별도 eval-exclusion-integrity-v2에 최종 source와 ABA 실행 결과를 보존했다.
  정상 fixture는 수용하고 hash 계산 중만 원본을 복원하는 변조 사본은 거절했다.
- 독립 최종 검토 53 pass / 1 skip, captured manifest bytes의 digest binding과
  v2 변조 거절·원본 session/digest·최종 source bytes 일치를 확인했다.
- 문서 15 pass / 1 Windows-bash skip, 변경 파일 secrets scanner 새 검출 0.

위 데이터는 synthetic host fixture이며 실제 모델 PC의 126프레임 평가 세트가 아니다.
실제 고정 세트, 모델 PC 전체 job, READY/intake/shadow/rollback 재검증과
객체 촬영 그룹 분할·사람 검수·새 데이터셋/모델 학습은 계속 남아 있다.
source/host 증거를 장치/현장 수용으로 확대하지 않는다. 기존 secrets guard 실패도 유지한다.
